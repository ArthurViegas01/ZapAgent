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
    state_with_match["appointment"] = {
        "title": "Atendimento",
        "starts_at": "2026-05-10T10:00:00-03:00",
        "ends_at": "2026-05-10T10:30:00-03:00",
    }
    diff = check_confidence(state_with_match)
    assert diff["next_action"] == "schedule"


def test_scheduling_without_appointment_falls_through_to_respond(
    state_with_match: AgentState,
) -> None:
    """Scheduling intent without slot extraction must NOT silently book a
    placeholder appointment -- let the LLM ask for the missing slot instead.
    """
    state_with_match["intent"] = Intent.SCHEDULING
    # No "appointment" key -- generate_response did not extract a slot.
    diff = check_confidence(state_with_match)
    assert diff["next_action"] == "respond"


def test_scheduling_without_appointment_responds_even_on_low_faq_score(
    base_state: AgentState,
) -> None:
    """Regression for the 2026-05-24 e2e test: a real `agendar` message
    with no FAQ match used to route to handoff because score=0.4 < 0.65,
    even though the right next step is to ask for the missing slot.
    """
    base_state["intent"] = Intent.SCHEDULING
    base_state["faq_matches"] = []  # no match -> default 0.4 score
    # No "appointment" key.
    diff = check_confidence(base_state)
    assert diff["next_action"] == "respond"
    assert diff["confidence"] == 1.0


def test_greeting_responds_with_full_confidence(base_state: AgentState) -> None:
    """Casual greetings cosine-miss every FAQ row; per-intent rules
    must override the score-based handoff path so 'Oi' gets a reply,
    not a human-attendant hand-off.
    """
    base_state["intent"] = Intent.GREETING
    base_state["faq_matches"] = []
    diff = check_confidence(base_state)
    assert diff["next_action"] == "respond"
    assert diff["confidence"] == 1.0


def test_low_confidence_routes_to_handoff(base_state: AgentState) -> None:
    base_state["intent"] = Intent.OTHER
    base_state["faq_matches"] = []  # no match -> default 0.4 score
    diff = check_confidence(base_state)
    assert diff["next_action"] == "handoff"
    assert diff["confidence"] < 0.65


def test_pricing_low_confidence_still_handoffs(base_state: AgentState) -> None:
    """PRICING is real information seeking: if there's no FAQ match,
    we don't have the answer and a human should pick it up. The
    per-intent rules must NOT short-circuit this branch.
    """
    base_state["intent"] = Intent.PRICING
    base_state["faq_matches"] = []
    diff = check_confidence(base_state)
    assert diff["next_action"] == "handoff"
    assert diff["confidence"] < 0.65


def test_opt_out_always_responds(base_state: AgentState) -> None:
    base_state["intent"] = Intent.OPT_OUT
    base_state["faq_matches"] = []
    diff = check_confidence(base_state)
    assert diff["next_action"] == "respond"
    assert diff["confidence"] == 1.0
