"""Integration tests for the compiled LangGraph DAG.

All tests run in offline mode:
  - No ANTHROPIC_API_KEY -> generate_response uses deterministic fallback.
  - No db_pool -> retrieve_context returns empty stubs.

Scheduling-branch routing requires a real DB (integration test) because
retrieve_context overwrites faq_matches with live DB results.
"""

from __future__ import annotations

import pytest

from src.agent.graph import build_graph
from src.agent.state import AgentState


@pytest.fixture
def graph():
    return build_graph()


async def _run(graph, state: AgentState) -> dict:
    config = {
        "configurable": {
            "thread_id": state["tenant_id"] + ":" + state["conversation_id"],
        }
    }
    return await graph.ainvoke(state, config=config)


# ---------------------------------------------------------------------------
# Routing assertions
# ---------------------------------------------------------------------------


async def test_graph_routes_handoff_for_unknown_intent(
    graph, base_state: AgentState
) -> None:
    """Garbage input -> no keyword match -> low confidence -> handoff branch."""
    base_state["user_message"] = "asdfghjkl"
    final = await _run(graph, base_state)
    assert final["next_action"] == "handoff"
    assert "atendente humano" in final["response"]
    assert final["handoff_reason"].startswith("low_confidence:")


async def test_graph_responds_to_greeting(graph, base_state: AgentState) -> None:
    """Greeting intent is classified correctly; response is populated."""
    base_state["user_message"] = "Bom dia!"
    final = await _run(graph, base_state)
    assert final["intent"].value == "greeting"
    assert "response" in final


async def test_graph_scheduling_intent_classified_correctly(
    graph, base_state: AgentState
) -> None:
    """Scheduling intent is classified; in offline mode routes to handoff (no DB)."""
    base_state["user_message"] = "Quero agendar uma consulta amanha"
    final = await _run(graph, base_state)
    assert final["intent"].value == "scheduling"
    # Offline: retrieve_context returns [] -> confidence=0.4 < threshold -> handoff.
    # Full schedule-branch routing is tested in tests/integration/.
    assert "response" in final


async def test_graph_records_token_usage(graph, base_state: AgentState) -> None:
    final = await _run(graph, base_state)
    assert "token_usage" in final
    assert set(final["token_usage"].keys()) == {"input", "output", "cached"}
    assert all(isinstance(v, int) for v in final["token_usage"].values())


async def test_graph_invokes_all_expected_pre_routing_nodes(
    graph, base_state: AgentState
) -> None:
    """Every pre-routing node must run regardless of which branch is taken."""
    final = await _run(graph, base_state)
    assert "intent" in final
    assert "faq_matches" in final
    assert "history" in final
    assert "response" in final
    assert "confidence" in final
    assert "next_action" in final


async def test_graph_opt_out_routes_to_respond(graph, base_state: AgentState) -> None:
    """OPT_OUT intent always resolves to respond, never handoff."""
    base_state["user_message"] = "PARAR"
    final = await _run(graph, base_state)
    assert final["intent"].value == "opt_out"
    assert final["next_action"] == "respond"


async def test_graph_handoff_sets_reason_and_timestamp(
    graph, base_state: AgentState
) -> None:
    """handoff_human node must populate handoff_reason and handoff_notified_at."""
    base_state["user_message"] = "asdfghjkl"
    final = await _run(graph, base_state)
    assert final.get("handoff_reason", "").startswith("low_confidence:")
    assert "handoff_notified_at" in final
