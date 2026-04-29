"""Typed state passed between LangGraph nodes.

`AgentState` is the contract. Every node accepts a state dict and returns a
*partial* state dict that LangGraph merges back. Tests assert on the shape of
that diff, not on global side effects.
"""

from __future__ import annotations

import sys
from typing import Any, TypedDict

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    # Compatibility shim for Python 3.10 (used in CI / local dev with 3.10).
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


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
    ends_at: str    # ISO 8601
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
    history: list[dict[str, Any]]    # prior {role, content} turns

    # -- Filled by generate_response --------------------------------------
    response: str
    token_usage: dict[str, int]      # {input, output, cached}

    # -- Filled by check_confidence ---------------------------------------
    confidence: float
    next_action: str                  # respond | schedule | handoff

    # -- Filled by schedule_appointment ----------------------------------
    appointment: AppointmentDraft
    appointment_id: str               # populated after Calendar insert

    # -- Filled by handoff_human ------------------------------------------
    handoff_reason: str
    handoff_notified_at: str          # ISO 8601

    # -- Optional: injected by router before graph.invoke -----------------
    tenant_settings: dict[str, str]   # name, persona, business_hours, phone
