"""generate_response - async: call Claude Haiku with a parametrized system prompt.

Production path (requires ANTHROPIC_API_KEY):
  - System prompt built from tenant_settings in state (name, persona, hours, phone).
  - User turn prefixed with top-k FAQ matches and the last N conversation turns.
  - When intent=SCHEDULING: slot-filling pass extracts date/time/service before
    generating the reply. Incomplete slots trigger a clarifying question.
  - Real token_usage (input / output / cache_read) returned for cost tracking.

Offline / test path (no API key set): deterministic fallback texts so that
the graph can run end-to-end and existing test assertions stay green.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from anthropic import AsyncAnthropic
from langchain_core.runnables import RunnableConfig

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState, AppointmentDraft, FaqMatch, Intent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Offline fallback texts
# ---------------------------------------------------------------------------

_GREETING_REPLY = "Olá! Como posso ajudar você hoje?"
_FALLBACK_REPLY = "Obrigado pela mensagem! Vou repassar para um atendente humano em instantes."
_OPT_OUT_REPLY = (
    "Tudo bem! Removemos voce da nossa lista de mensagens. "
    "Se quiser retomar o contato, e so nos enviar uma mensagem."
)

# ---------------------------------------------------------------------------
# System prompt (general)
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = (
    "Voce e {name}, um assistente virtual de atendimento ao cliente via WhatsApp.\n\n"
    "Persona: {persona}\n"
    "Horario de atendimento: {business_hours}\n"
    "Telefone de contato: {phone}\n\n"
    "Responda de forma clara, educada e concisa em portugues brasileiro.\n"
    "Nunca invente informacoes - se nao souber, diga que vai verificar com a equipe.\n"
    "Limite sua resposta a {max_chars} caracteres.\n"
)

_DEFAULT_TENANT_SETTINGS: dict[str, str] = {
    "name": "Assistente Virtual",
    "persona": "Atendente educado e prestativo.",
    "business_hours": "Segunda a sexta, 9h as 18h.",
    "phone": "nao disponivel",
}

# ---------------------------------------------------------------------------
# Slot-filling prompt
# ---------------------------------------------------------------------------

_SLOT_SYSTEM = (
    "Voce e um extrator de informacoes de agendamento para um assistente de WhatsApp.\n"
    "Analise o historico da conversa e extraia os slots necessarios para o agendamento.\n\n"
    "Hoje e {today} (dia da semana: {weekday}).\n\n"
    "Retorne APENAS um objeto JSON valido, sem texto adicional, com esta estrutura:\n"
    "{{\n"
    '  "slots_complete": true/false,\n'
    '  "date": "YYYY-MM-DD ou null",\n'
    '  "time": "HH:MM ou null",\n'
    '  "service": "nome do servico ou null",\n'
    '  "duration_minutes": 30,\n'
    '  "follow_up": "pergunta para o cliente se slots incompletos, caso contrario null"\n'
    "}}\n\n"
    "Regras:\n"
    "- slots_complete = true somente se date E time estiverem preenchidos\n"
    "- Interprete referencias relativas: 'amanha', 'semana que vem', 'as 15h', etc.\n"
    "- Se o cliente so informou o servico mas nao data/hora, slots_complete = false\n"
    "- follow_up deve ser amigavel, em pt-BR, pedindo apenas o que falta\n"
)

_WEEKDAYS_PT = [
    "segunda-feira",
    "terca-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sabado",
    "domingo",
]


def _build_system_prompt(state: AgentState) -> str:
    settings = get_settings()
    ts: dict[str, str] = state.get("tenant_settings", _DEFAULT_TENANT_SETTINGS)  # type: ignore[arg-type]
    return _SYSTEM_TEMPLATE.format(
        name=ts.get("name", _DEFAULT_TENANT_SETTINGS["name"]),
        persona=ts.get("persona", _DEFAULT_TENANT_SETTINGS["persona"]),
        business_hours=ts.get("business_hours", _DEFAULT_TENANT_SETTINGS["business_hours"]),
        phone=ts.get("phone", _DEFAULT_TENANT_SETTINGS["phone"]),
        max_chars=settings.agent_response_max_chars,
    )


def _faq_context_block(matches: list[FaqMatch]) -> str:
    if not matches:
        return ""
    lines = ["Informações relevantes extraídas do FAQ:"]
    for m in matches:
        lines.append("P: " + m["question"] + "\nR: " + m["answer"])
    return "\n\n".join(lines)


def _build_messages(state: AgentState) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in state.get("history", []):
        messages.append({"role": str(turn["role"]), "content": str(turn["content"])})
    faq_block = _faq_context_block(state.get("faq_matches", []))
    user_content = state.get("user_message", "")
    if faq_block:
        user_content = faq_block + "\n\n---\nMensagem do cliente: " + user_content
    messages.append({"role": "user", "content": user_content})
    return messages


def _conversation_text(state: AgentState) -> str:
    """Flatten history + current message for slot extraction."""
    parts: list[str] = []
    for turn in state.get("history", []):
        role = "Cliente" if turn["role"] == "user" else "Assistente"
        parts.append(f"{role}: {turn['content']}")
    parts.append("Cliente: " + state.get("user_message", ""))
    return "\n".join(parts)


def _parse_slot_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM output (may have markdown fences)."""
    raw = raw.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _slots_to_draft(slots: dict[str, Any], contact_phone: str) -> AppointmentDraft | None:
    """Convert extracted slots to an AppointmentDraft, or None if date/time missing."""
    date_str: str | None = slots.get("date")
    time_str: str | None = slots.get("time")
    if not date_str or not time_str:
        return None
    try:
        starts = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        # Assume Sao Paulo if naive (MVP simplification)
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=UTC)
        duration = int(slots.get("duration_minutes") or 30)
        ends = starts + timedelta(minutes=duration)
        service = slots.get("service") or "Atendimento"
        return AppointmentDraft(
            title=f"{service} - {contact_phone}",
            starts_at=starts.isoformat(),
            ends_at=ends.isoformat(),
            notes=f"Agendado via WhatsApp. Servico: {service}",
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


async def generate_response(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, object]:
    """Produce the assistant reply via Claude Haiku.

    For SCHEDULING intents, runs a slot-filling pass first:
    - Slots complete  -> fills state.appointment, sends confirmation
    - Slots missing   -> sends a clarifying question, leaves appointment unset

    Returns:
        Partial state with response (str), token_usage, and optionally
        appointment (AppointmentDraft) when scheduling slots are complete.
    """
    settings = get_settings()

    # OPT_OUT: return confirmation immediately, no LLM call needed.
    if state.get("intent") == Intent.OPT_OUT:
        return {"response": _OPT_OUT_REPLY, "token_usage": {"input": 0, "output": 0, "cached": 0}}

    # ------------------------------------------------------------------
    # Offline / test path
    # ------------------------------------------------------------------
    if not settings.anthropic_api_key:
        intent = state.get("intent", Intent.OTHER)
        matches = state.get("faq_matches", [])
        if intent == Intent.GREETING:
            text = _GREETING_REPLY
        elif intent == Intent.SCHEDULING:
            text = "Claro! Para agendar, me informe a data e o horario de sua preferencia."
        elif matches:
            text = matches[0]["answer"]
        else:
            text = _FALLBACK_REPLY
        logger.debug(
            "generate_response.offline_fallback",
            tenant_id=state.get("tenant_id"),
            intent=str(intent),
        )
        return {"response": text, "token_usage": {"input": 0, "output": 0, "cached": 0}}

    # ------------------------------------------------------------------
    # Production path
    # ------------------------------------------------------------------
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    total_usage: dict[str, int] = {"input": 0, "output": 0, "cached": 0}

    # ------------------------------------------------------------------
    # Slot-filling pass (only for SCHEDULING intent, only if no draft yet)
    # ------------------------------------------------------------------
    appointment_draft: AppointmentDraft | None = state.get("appointment")  # type: ignore[assignment]

    if state.get("intent") == Intent.SCHEDULING and appointment_draft is None:
        now = datetime.now(tz=UTC)
        slot_system = _SLOT_SYSTEM.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=_WEEKDAYS_PT[now.weekday()],
        )
        conv_text = _conversation_text(state)

        try:
            slot_resp = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=512,
                system=slot_system,
                messages=[{"role": "user", "content": conv_text}],
            )
            slot_raw = slot_resp.content[0].text  # type: ignore[union-attr]
            u = slot_resp.usage
            total_usage["input"] += u.input_tokens
            total_usage["output"] += u.output_tokens
            total_usage["cached"] += getattr(u, "cache_read_input_tokens", 0)

            slots = _parse_slot_json(slot_raw)
            logger.info(
                "generate_response.slots_extracted", tenant_id=state.get("tenant_id"), slots=slots
            )

            if slots.get("slots_complete"):
                appointment_draft = _slots_to_draft(slots, state.get("contact_phone", ""))
                if appointment_draft:
                    # All slots filled — confirm and let check_confidence route to schedule
                    try:
                        from datetime import datetime as _dt

                        dt = _dt.fromisoformat(appointment_draft["starts_at"])
                        weekdays = [
                            "Segunda",
                            "Terca",
                            "Quarta",
                            "Quinta",
                            "Sexta",
                            "Sabado",
                            "Domingo",
                        ]
                        friendly = dt.strftime(weekdays[dt.weekday()] + ", %d/%m as %H:%M")
                    except Exception:
                        friendly = appointment_draft.get("starts_at", "")
                    confirm_text = (
                        "Perfeito! Vou confirmar seu agendamento para "
                        + friendly
                        + ". Um momento enquanto registro..."
                    )
                    return {
                        "response": confirm_text,
                        "appointment": appointment_draft,
                        "token_usage": total_usage,
                    }
            else:
                # Slots incomplete — return follow-up question directly
                follow_up = (
                    slots.get("follow_up")
                    or "Para agendar, pode me informar a data e o horario de sua preferencia?"
                )
                return {"response": follow_up, "token_usage": total_usage}

        except Exception as exc:
            logger.error("generate_response.slot_extraction_failed", error=str(exc))
            # Fall through to general response

    # ------------------------------------------------------------------
    # General response pass
    # ------------------------------------------------------------------
    system = _build_system_prompt(state)
    messages = _build_messages(state)

    api_response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=system,
        messages=messages,
    )

    text = api_response.content[0].text  # type: ignore[union-attr]
    u2 = api_response.usage
    total_usage["input"] += u2.input_tokens
    total_usage["output"] += u2.output_tokens
    total_usage["cached"] += getattr(u2, "cache_read_input_tokens", 0)

    logger.info(
        "generate_response.done",
        tenant_id=state.get("tenant_id"),
        model=settings.anthropic_model,
        response_len=len(text),
        token_usage=total_usage,
    )

    result: dict[str, object] = {"response": text, "token_usage": total_usage}
    if appointment_draft:
        result["appointment"] = appointment_draft
    return result
