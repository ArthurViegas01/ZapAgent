"""schedule_appointment — call Google Calendar to create the event.

Real implementation:
  - Look up the tenant's `integrations.google_calendar` row
  - Refresh the OAuth token if expiring soon
  - Call calendar.events.insert with the AppointmentDraft from state
  - Persist a row in `appointments` and return its id

Placeholder fabricates a deterministic id so downstream code paths can be
exercised in tests without hitting the network.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from ...core.logging import get_logger
from ..state import AgentState, AppointmentDraft

logger = get_logger(__name__)


def _placeholder_draft(state: AgentState) -> AppointmentDraft:
    """Stub draft used until the slot-filling LLM call lands."""
    starts = datetime.now(tz=timezone.utc) + timedelta(days=1)
    ends = starts + timedelta(minutes=30)
    return AppointmentDraft(
        title=f"Atendimento — {state.get('contact_phone', 'sem telefone')}",
        starts_at=starts.isoformat(),
        ends_at=ends.isoformat(),
        notes=state.get("user_message", ""),
    )


def schedule_appointment(state: AgentState) -> dict[str, object]:
    """Create the calendar event and return the resulting state diff.

    Returns:
        Partial state with `appointment`, `appointment_id`, and a confirmation
        `response` overriding the previous one.
    """
    draft = state.get("appointment") or _placeholder_draft(state)
    appointment_id = f"apt_{uuid.uuid4().hex[:12]}"
    confirmation = (
        "Agendamento confirmado para "
        f"{draft.get('starts_at')}. Te aguardamos!"
    )

    logger.info(
        "schedule_appointment.done",
        tenant_id=state.get("tenant_id"),
        appointment_id=appointment_id,
        starts_at=draft.get("starts_at"),
    )
    return {
        "appointment": draft,
        "appointment_id": appointment_id,
        "response": confirmation,
    }
