"""generate_response — async: call Claude Haiku with a parametrized system prompt.

Production path (requires ANTHROPIC_API_KEY):
  - System prompt built from tenant_settings in state (name, persona, hours, phone).
    When not yet populated (Etapa 1), sane defaults are used.
  - User turn prefixed with top-k FAQ matches and the last N conversation turns.
  - Real token_usage (input / output / cache_read) returned for cost tracking.

Offline / test path (no API key set): deterministic fallback texts so that
the graph can run end-to-end and existing test assertions stay green.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from langchain_core.runnables import RunnableConfig

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState, FaqMatch, Intent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Offline fallback texts
# ---------------------------------------------------------------------------

_GREETING_REPLY = "Olá! Como posso ajudar você hoje?"
_FALLBACK_REPLY = (
    "Obrigado pela mensagem! Vou repassar para um atendente humano em instantes."
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = (
    "Você é {name}, um assistente virtual de atendimento ao cliente via WhatsApp.\n\n"
    "Persona: {persona}\n"
    "Horário de atendimento: {business_hours}\n"
    "Telefone de contato: {phone}\n\n"
    "Responda de forma clara, educada e concisa em português brasileiro.\n"
    "Nunca invente informações — se não souber, diga que vai verificar com a equipe.\n"
    "Limite sua resposta a {max_chars} caracteres.\n"
)

_DEFAULT_TENANT_SETTINGS: dict[str, str] = {
    "name": "Assistente Virtual",
    "persona": "Atendente educado e prestativo.",
    "business_hours": "Segunda a sexta, 9h às 18h.",
    "phone": "não disponível",
}


def _build_system_prompt(state: AgentState) -> str:
    settings = get_settings()
    # tenant_settings will be populated from DB in Etapa 2; fall back to
    # defaults so the node works standalone during Etapa 1.
    ts: dict[str, str] = state.get("tenant_settings", _DEFAULT_TENANT_SETTINGS)  # type: ignore[arg-type]
    return _SYSTEM_TEMPLATE.format(
        name=ts.get("name", _DEFAULT_TENANT_SETTINGS["name"]),
        persona=ts.get("persona", _DEFAULT_TENANT_SETTINGS["persona"]),
        business_hours=ts.get("business_hours", _DEFAULT_TENANT_SETTINGS["business_hours"]),
        phone=ts.get("phone", _DEFAULT_TENANT_SETTINGS["phone"]),
        max_chars=settings.agent_response_max_chars,
    )


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------


def _faq_context_block(matches: list[FaqMatch]) -> str:
    """Format FAQ matches as a context block prepended to the user turn."""
    if not matches:
        return ""
    lines = ["Informações relevantes extraídas do FAQ:"]
    for m in matches:
        lines.append("P: " + m["question"] + "\nR: " + m["answer"])
    return "\n\n".join(lines)


def _build_messages(state: AgentState) -> list[dict[str, str]]:
    """Compose the messages list for the Anthropic API call.

    Layout:
      [history turns...]  ->  user turn (optionally prefixed with FAQ context)
    """
    messages: list[dict[str, str]] = []

    # Prior conversation turns (oldest-first, as returned by retrieve_context).
    for turn in state.get("history", []):
        messages.append({"role": str(turn["role"]), "content": str(turn["content"])})

    # Current user message, optionally enriched with FAQ context.
    faq_block = _faq_context_block(state.get("faq_matches", []))
    user_content = state.get("user_message", "")
    if faq_block:
        user_content = faq_block + "\n\n---\nMensagem do cliente: " + user_content

    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


async def generate_response(
    state: AgentState,
    config: RunnableConfig | None = None,  # noqa: ARG001
) -> dict[str, object]:
    """Produce the assistant reply via Claude Haiku.

    Args:
        state: must carry user_message, intent, faq_matches, and optionally
            history and tenant_settings.
        config: unused — present so LangGraph can inject RunnableConfig if
            needed in future (e.g. for streaming callbacks).

    Returns:
        Partial state with response (str) and token_usage
        ({input, output, cached} int counts).
    """
    settings = get_settings()

    # ------------------------------------------------------------------
    # Offline / test path — no API key configured.
    # Deterministic fallback so tests pass without network calls.
    # ------------------------------------------------------------------
    if not settings.anthropic_api_key:
        intent = state.get("intent", Intent.OTHER)
        matches = state.get("faq_matches", [])
        if intent == Intent.GREETING:
            text = _GREETING_REPLY
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
    # Production path — call Claude Haiku.
    # ------------------------------------------------------------------
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    system = _build_system_prompt(state)
    messages = _build_messages(state)

    api_response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=system,
        messages=messages,
    )

    text = api_response.content[0].text  # type: ignore[union-attr]
    usage = api_response.usage
    token_usage: dict[str, int] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cached": getattr(usage, "cache_read_input_tokens", 0),
    }

    logger.info(
        "generate_response.done",
        tenant_id=state.get("tenant_id"),
        model=settings.anthropic_model,
        response_len=len(text),
        token_usage=token_usage,
    )
    return {"response": text, "token_usage": token_usage}
