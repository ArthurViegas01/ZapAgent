"""Unit tests for the schedule_appointment node."""

from __future__ import annotations

from src.agent.nodes.schedule_appointment import schedule_appointment
from src.agent.state import AgentState


def test_schedule_appointment_creates_id_and_confirmation(base_state: AgentState) -> None:
    diff = schedule_appointment(base_state)
    assert diff["appointment_id"].startswith("apt_")
    assert "appointment" in diff
    appointment = diff["appointment"]
    assert "starts_at" in appointment and "ends_at" in appointment
    assert appointment["starts_at"] < appointment["ends_at"]
    assert "confirmado" in diff["response"].lower()


def test_schedule_appointment_uses_existing_draft(base_state: AgentState) -> None:
    base_state["appointment"] = {
        "title": "Corte",
        "starts_at": "2026-05-01T10:00:00+00:00",
        "ends_at": "2026-05-01T10:30:00+00:00",
        "notes": "manual",
    }
    diff = schedule_appointment(base_state)
    assert diff["appointment"]["title"] == "Corte"
    assert "2026-05-01T10:00:00+00:00" in diff["response"]
