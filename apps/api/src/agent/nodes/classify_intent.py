"""classify_intent — assign an Intent to the inbound user message.

Real implementation will call Claude Haiku with a tight system prompt and
JSON schema output. The placeholder uses keyword heuristics so the rest of
the graph can be wired up and tested without an API key.
"""

from __future__ import annotations

from ...core.logging import get_logger
from ..state import AgentState, Intent

logger = get_logger(__name__)


# Keyword heuristics — Portuguese (pt-BR) tuned. The LLM-backed version will
# replace this entirely; the keywords stay only as a fast-path / fallback.
#
# ORDER MATTERS: more specific / higher-priority intents must appear first.
# E.g. PRICING before SCHEDULING so "Quanto custa a consulta?" hits PRICING
# (on "quanto custa") before SCHEDULING (on "consulta").
_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.OPT_OUT: ("parar", "sair", "cancelar inscri", "remover", "descadastrar"),
    Intent.PRICING: ("preço", "preco", "valor", "custo", "quanto custa", "tabela"),
    Intent.SCHEDULING: (
        "agendar", "marcar", "horário", "horario", "consulta", "encaixe", "remarcar",
    ),
    Intent.GREETING: ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"),
    Intent.INFORMATION: ("endereço", "endereco", "horário de funcionamento", "telefone"),
}


def _heuristic_intent(message: str) -> Intent:
    lowered = message.lower().strip()
    for intent, terms in _KEYWORDS.items():
        if any(term in lowered for term in terms):
            return intent
    return Intent.OTHER


def classify_intent(state: AgentState) -> dict[str, object]:
    """Classify the inbound user message into an Intent.

    Args:
        state: must carry `user_message` and `tenant_id`.

    Returns:
        Partial state with `intent` set.
    """
    message = state.get("user_message", "")
    if not message:
        # An empty message goes straight to handoff rather than wasting an
        # LLM call. The router will see Intent.OTHER + low confidence.
        logger.warning("classify_intent.empty_message", tenant_id=state.get("tenant_id"))
        return {"intent": Intent.OTHER}

    intent = _heuristic_intent(message)
    logger.info(
        "classify_intent.done",
        tenant_id=state.get("tenant_id"),
        intent=intent.value,
        message_len=len(message),
    )
    return {"intent": intent}
