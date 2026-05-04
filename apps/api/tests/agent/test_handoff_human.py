"""Unit tests for the handoff_human node.

Tests run without a DB pool so they exercise the offline path:
the conversation status UPDATE and Evolution notification are skipped.
"""

from __future__ import annotations

import pytest

from src.agent.nodes.handoff_human import handoff_human
from src.agent.state import AgentState, Intent


@pytest.mark.asyncio
async def test_handoff_records_low_confidence_reason(base_state: AgentState) -> None:
    base_state["confidence"] = 0.3
    base_state["intent"] = Intent.OTHER
    diff = await handoff_human(base_state)
    assert diff["handoff_reason"].startswith("low_confidence:")
    assert "atendente humano" in diff["response"]
    assert "handoff_notified_at" in diff


@pytest.mark.asyncio
async def test_handoff_records_intent_reason_when_confidence_ok(base_state: AgentState) -> None:
    base_state["confidence"] = 0.9
    base_state["intent"] = Intent.OTHER
    diff = await handoff_human(base_state)
    assert diff["handoff_reason"].startswith("intent:")


@pytest.mark.asyncio
async def test_handoff_returns_standby_response(base_state: AgentState) -> None:
    diff = await handoff_human(base_state)
    assert isinstance(diff["response"], str)
    assert len(diff["response"]) > 10
