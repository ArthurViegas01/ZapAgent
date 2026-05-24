"""Typed state passed between LangGraph nodes.

`AgentState` is the contract. Every node accepts a state dict and returns a
*partial* state dict that LangGraph merges back. Tests assert on the shape of
that diff, not on global side effects.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

# Project requires Python >= 3.11 (pyproject.toml) so StrEnum is always
# available natively; the prior compat shim for 3.10 has been removed.


class Intent(StrEnum):
    """Classified intent for an inbound message."""

    SCHEDULING = "scheduling"
    PRICING = "pricing"
    INFORMATION = "information"
    GREETING = "greeting"
    OPT_OUT = "opt_out"
    OTHER = "other"


class FaqMatch(TypedDict):
    """A single FAQ retrieval result."""

    id: str
    question: str
    answer: str
    score: float


class AppointmentDraft(TypedDict, total=False):
    """Slot-filled appointment proposal extracted from the conversation."""

    title: str
    starts_at: str  # ISO 8601
    ends_at: str  # ISO 8601
    notes: str


class AgentState(TypedDict, total=False):
    """State that flows through the LangGraph DAG.

    Required keys are set by the caller before invoking the graph; optional
    keys are filled in as nodes run.
    """

    # -- Required input ---------------------------------------------------
    tenant_id: str
    conversation_id: str
    contact_phone: str
    user_message: str

    # -- Filled by classify_intent ----------------------------------------
    intent: Intent

    # -- Filled by retrieve_context ---------------------------------------
    faq_matches: list[FaqMatch]
    history: list[dict[str, Any]]  # prior {role, content} turns

    # -- Filled by generate_response --------------------------------------
    response: str
    token_usage: dict[str, int]  # {input, output, cached}

    # -- Filled by check_confidence ---------------------------------------
    confidence: float
    next_action: str  # respond | schedule | handoff

    # -- Filled by schedule_appointment ----------------------------------
    appointment: AppointmentDraft
    appointment_id: str  # populated after Calendar insert

    # -- Filled by handoff_human ------------------------------------------
    handoff_reason: str
    handoff_notified_at: str  # ISO 8601

    # -- Optional: injected by router before graph.invoke -----------------
    tenant_settings: dict[str, str]  # name, persona, business_hours, phone
