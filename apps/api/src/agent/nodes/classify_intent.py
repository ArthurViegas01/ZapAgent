"""classify_intent - assign an Intent to the inbound user message.

Production path (requires ANTHROPIC_API_KEY):
  - Calls Claude Haiku with a tight system prompt and JSON schema output.
  - Returns the intent + confidence directly from the model.
  - Falls back to keyword heuristics on any API error.

Offline / test path (no API key set):
  - Runs keyword heuristics synchronously so tests pass without network calls.
"""

from __future__ import annotations

import json

from ...core.logging import get_logger
from ..state import AgentState, Intent

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Keyword heuristics - Portuguese (pt-BR) tuned.
# Used as fallback if the LLM call fails, and as safety net for OPT_OUT.
# ORDER MATTERS: more specific / higher-priority intents must appear first.
# ---------------------------------------------------------------------------

_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.OPT_OUT: ("parar", "sair", "cancelar inscri", "remover", "descadastrar", "nao quero mais", "nao quero receber"),
    Intent.PRICING: ("preco", "valor", "custo", "quanto custa", "tabela", "orcamento", "preco"),
    Intent.SCHEDULING: (
        "agendar", "marcar", "horario", "consulta", "encaixe", "remarcar",
        "disponibilidade", "quando posso",
    ),
    Intent.GREETING: ("oi", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom"),
    Intent.INFORMATION: ("endereco", "horario de funcionamento", "telefone", "onde fica"),
}

# Also check with accents (lowercased)
_KEYWORDS_ACCENT: dict[Intent, tuple[str, ...]] = {
    Intent.OPT_OUT: ("parar", "sair", "cancelar inscri", "remover", "descadastrar", "não quero mais"),
    Intent.PRICING: ("preço", "valor", "custo", "quanto custa", "tabela", "orçamento"),
    Intent.SCHEDULING: (
        "agendar", "marcar", "horário", "consulta", "encaixe", "remarcar",
        "disponibilidade", "quando posso",
    ),
    Intent.GREETING: ("oi", "olá", "bom dia", "boa tarde", "boa noite"),
    Intent.INFORMATION: ("endereço", "horário de funcionamento", "telefone", "onde fica"),
}


def _heuristic_intent(message: str) -> Intent:
    lowered = message.lower().strip()
    for intent, terms in _KEYWORDS_ACCENT.items():
        if any(term in lowered for term in terms):
            return intent
    for intent, terms in _KEYWORDS.items():
        if any(term in lowered for term in terms):
            return intent
    return Intent.OTHER


# ---------------------------------------------------------------------------
# LLM-backed classification
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Voce e um classificador de intencoes para um chatbot de atendimento ao cliente via WhatsApp.\n\n"
    "Analise a mensagem do usuario e retorne EXATAMENTE um JSON com:\n"
    '- "intent": uma das opcoes abaixo\n'
    '- "confidence": numero entre 0.0 e 1.0\n\n'
    "Opcoes de intent:\n"
    '- "scheduling"   -> cliente quer agendar, remarcar ou cancelar um servico\n'
    '- "pricing"      -> cliente pergunta sobre precos, valores, pacotes\n'
    '- "information"  -> cliente pede informacoes gerais (endereco, horarios, servicos)\n'
    '- "greeting"     -> saudacao ou mensagem de abertura\n'
    '- "opt_out"      -> cliente quer parar de receber mensagens\n'
    '- "other"        -> qualquer outra coisa\n\n'
    'Responda APENAS com o JSON, sem texto adicional. Exemplo:\n'
    '{"intent": "scheduling", "confidence": 0.95}'
)


async def _llm_classify(message: str, api_key: str, model: str) -> tuple[Intent, float]:
    """Call Claude Haiku and parse the JSON response. Returns (intent, confidence)."""
    from anthropic import AsyncAnthropic  # noqa: PLC0415

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=64,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )

    raw = response.content[0].text.strip()  # type: ignore[union-attr]
    # Strip potential markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw)
    intent_str: str = parsed.get("intent", "other").lower()
    confidence: float = float(parsed.get("confidence", 0.7))

    try:
        intent = Intent(intent_str)
    except ValueError:
        intent = Intent.OTHER

    return intent, confidence


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


async def classify_intent(state: AgentState) -> dict[str, object]:
    """Classify the inbound user message into an Intent.

    Args:
        state: must carry `user_message` and `tenant_id`.

    Returns:
        Partial state with `intent` set (and optionally `confidence` pre-set
        from the LLM when available).
    """
    from ...core.config import get_settings  # noqa: PLC0415

    message = state.get("user_message", "")
    if not message:
        logger.warning("classify_intent.empty_message", tenant_id=state.get("tenant_id"))
        return {"intent": Intent.OTHER}

    settings = get_settings()

    # ------------------------------------------------------------------
    # Safety-first: OPT_OUT always goes through keyword check first so
    # a user typing "parar" is never missed due to an LLM error.
    # ------------------------------------------------------------------
    lowered = message.lower().strip()
    opt_out_terms = _KEYWORDS_ACCENT[Intent.OPT_OUT]
    if any(term in lowered for term in opt_out_terms):
        logger.info("classify_intent.opt_out_keyword", tenant_id=state.get("tenant_id"))
        return {"intent": Intent.OPT_OUT}

    # ------------------------------------------------------------------
    # Production path - Claude Haiku with JSON schema output.
    # ------------------------------------------------------------------
    if settings.anthropic_api_key:
        try:
            intent, confidence = await _llm_classify(
                message,
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
            logger.info(
                "classify_intent.llm",
                tenant_id=state.get("tenant_id"),
                intent=intent.value,
                confidence=confidence,
                message_len=len(message),
            )
            return {"intent": intent, "confidence": confidence}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "classify_intent.llm_error",
                tenant_id=state.get("tenant_id"),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Offline / fallback path - keyword heuristics.
    # ------------------------------------------------------------------
    intent = _heuristic_intent(message)
    logger.info(
        "classify_intent.heuristic",
        tenant_id=state.get("tenant_id"),
        intent=intent.value,
        message_len=len(message),
    )
    return {"intent": intent}
