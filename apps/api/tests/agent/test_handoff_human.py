"""Unit tests for the handoff_human node."""

from __future__ import annotations

from src.agent.nodes.handoff_human import handoff_human
from src.agent.state import AgentState, Intent


def test_handoff_records_low_confidence_reason(base_state: AgentState) -> None:
    base_state["confidence"] = 0.3
    base_state["intent"] = Intent.OTHER
    diff = handoff_human(base_state)
    assert diff["handoff_reason"].startswith("low_confidence:")
    assert "atendente humano" in diff["response"]
    assert "handoff_notified_at" in diff


def test_handoff_records_intent_reason_when_confidence_ok(base_state: AgentState) -> None:
    base_state["confidence"] = 0.9
    base_state["intent"] = Intent.OTHER
    diff = handoff_human(base_state)
    assert diff["handoff_reason"].startswith("intent:")
