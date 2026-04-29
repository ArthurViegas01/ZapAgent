"""handoff_human — escalate to a human operator.

Real implementation:
  - Mark `conversations.status = 'handoff'`
  - Send a WhatsApp notification to the tenant owner's number
  - Send an email via Resend/Postmark as backup
  - Return a polite stand-by message to the contact

Placeholder records the reason and timestamps the notification without
performing any side effect.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...core.logging import get_logger
from ..state import AgentState

logger = get_logger(__name__)

_STANDBY_MESSAGE = (
    "Vou chamar um atendente humano para te ajudar com isso. "
    "Em instantes alguém retorna por aqui!"
)


def handoff_human(state: AgentState) -> dict[str, object]:
    """Notify operators and return the standby response."""
    confidence = state.get("confidence", 0.0)
    intent = state.get("intent")
    reason = (
        f"low_confidence:{confidence:.2f}"
        if confidence < 0.65
        else f"intent:{intent.value if intent else 'unknown'}"
    )

    notified_at = datetime.now(tz=timezone.utc).isoformat()
    logger.warning(
        "handoff_human.triggered",
        tenant_id=state.get("tenant_id"),
        conversation_id=state.get("conversation_id"),
        reason=reason,
    )
    return {
        "handoff_reason": reason,
        "handoff_notified_at": notified_at,
        "response": _STANDBY_MESSAGE,
    }
