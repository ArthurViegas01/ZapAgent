"""Build the LangGraph StateGraph.

The graph is intentionally small: classify → retrieve → generate → check,
then a conditional edge fans out to respond / schedule / handoff and
terminates. Tests use this builder to compile a graph against an in-memory
checkpointer; production wires `PostgresSaver` via `build_graph(checkpointer)`.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    check_confidence,
    classify_intent,
    generate_response,
    handoff_human,
    retrieve_context,
    schedule_appointment,
)
from .state import AgentState


def _route_after_confidence(state: AgentState) -> str:
    """Conditional edge selector after `check_confidence`.

    Maps the `next_action` string to the destination node name. Keeping the
    mapping here (rather than inside the node) keeps nodes pure and the
    routing logic discoverable.
    """
    action = state.get("next_action", "respond")
    return {
        "respond": END,
        "schedule": "schedule_appointment",
        "handoff": "handoff_human",
    }.get(action, END)


def build_graph(checkpointer: Any | None = None) -> Any:
    """Compile and return the LangGraph runnable.

    Args:
        checkpointer: a langgraph checkpointer. Defaults to MemorySaver, which
            is fine for tests and local dev. Production passes a PostgresSaver
            backed by the same database used by the rest of the app.
    """
    graph: StateGraph = StateGraph(AgentState)

    graph.add_node("classify_intent", classify_intent)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("generate_response", generate_response)
    graph.add_node("check_confidence", check_confidence)
    graph.add_node("schedule_appointment", schedule_appointment)
    graph.add_node("handoff_human", handoff_human)

    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "retrieve_context")
    graph.add_edge("retrieve_context", "generate_response")
    graph.add_edge("generate_response", "check_confidence")

    graph.add_conditional_edges(
        "check_confidence",
        _route_after_confidence,
        {
            END: END,
            "schedule_appointment": "schedule_appointment",
            "handoff_human": "handoff_human",
        },
    )

    graph.add_edge("schedule_appointment", END)
    graph.add_edge("handoff_human", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
