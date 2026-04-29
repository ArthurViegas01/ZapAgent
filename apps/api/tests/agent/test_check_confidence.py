"""Unit tests for the check_confidence node."""

from __future__ import annotations

from src.agent.nodes.check_confidence import check_confidence
from src.agent.state import AgentState, Intent


def test_high_score_routes_to_respond(state_with_match: AgentState) -> None:
    state_with_match["intent"] = Intent.INFORMATION
    diff = check_confidence(state_with_match)
    assert diff["next_action"] == "respond"
    assert diff["confidence"] >= 0.65


def test_scheduling_with_high_score_routes_to_schedule(state_with_match: AgentState) -> None:
    state_with_match["intent"] = Intent.SCHEDULING
    diff = check_confidence(state_with_match)
    assert diff["next_action"] == "schedule"


def test_low_confidence_routes_to_handoff(base_state: AgentState) -> None:
    base_state["intent"] = Intent.OTHER
    base_state["faq_matches"] = []  # no match -> default 0.4 score
    diff = check_confidence(base_state)
    assert diff["next_action"] == "handoff"
    assert diff["confidence"] < 0.65


def test_opt_out_always_responds(base_state: AgentState) -> None:
    base_state["intent"] = Intent.OPT_OUT
    base_state["faq_matches"] = []
    diff = check_confidence(base_state)
    assert diff["next_action"] == "respond"
