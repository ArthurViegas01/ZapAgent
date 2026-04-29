"""check_confidence — decide what to do next: reply, schedule, or hand off.

The decision is computed from:
  - top FAQ match score (proxy for retrieval confidence)
  - whether the response was the placeholder fallback
  - the classified intent (scheduling forces the schedule branch)

Returns a `confidence` score in [0, 1] and a `next_action` string used by the
conditional edge in graph.py.
"""

from __future__ import annotations

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState, Intent

logger = get_logger(__name__)


def _score_from_state(state: AgentState) -> float:
    matches = state.get("faq_matches", [])
    if matches:
        return float(max(m["score"] for m in matches))
    # No FAQ match: the LLM might still produce a reasonable reply, but we
    # default to a moderate score so the threshold can route as configured.
    return 0.4


def check_confidence(state: AgentState) -> dict[str, object]:
    """Compute confidence and pick the next action.

    Returns:
        Partial state with `confidence` and `next_action` in
        {"respond", "schedule", "handoff"}.
    """
    settings = get_settings()
    threshold = settings.agent_confidence_threshold

    intent = state.get("intent", Intent.OTHER)
    confidence = _score_from_state(state)

    if intent == Intent.OPT_OUT:
        # Opt-out is always handled (no LLM, no scheduling), but we route
        # to respond so the worker can persist the opt-out and stop replying.
        next_action = "respond"
    elif intent == Intent.SCHEDULING and confidence >= threshold:
        next_action = "schedule"
    elif confidence < threshold:
        next_action = "handoff"
    else:
        next_action = "respond"

    logger.info(
        "check_confidence.done",
        tenant_id=state.get("tenant_id"),
        intent=intent.value if isinstance(intent, Intent) else intent,
        confidence=round(confidence, 3),
        threshold=threshold,
        next_action=next_action,
    )
    return {"confidence": confidence, "next_action": next_action}
