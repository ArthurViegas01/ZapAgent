"""Unit tests for the retrieve_context node."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.agent.nodes  # noqa: F401 — loads node modules into sys.modules

_rc_mod = sys.modules["src.agent.nodes.retrieve_context"]

from src.agent.nodes.retrieve_context import retrieve_context
from src.agent.state import AgentState, FaqMatch
from src.core.config import get_settings

# ---------------------------------------------------------------------------
# Stub-path tests (no pool / no key)
# ---------------------------------------------------------------------------


async def test_retrieve_context_returns_expected_keys(base_state: AgentState) -> None:
    diff = await retrieve_context(base_state)
    assert set(diff.keys()) == {"faq_matches", "history"}
    assert isinstance(diff["faq_matches"], list)
    assert isinstance(diff["history"], list)


async def test_retrieve_context_stub_when_no_pool(base_state: AgentState) -> None:
    diff = await retrieve_context(base_state, config=None)
    assert diff["faq_matches"] == []
    assert diff["history"] == []


async def test_retrieve_context_stub_with_thread_id_only(base_state: AgentState) -> None:
    diff = await retrieve_context(
        base_state,
        config={"configurable": {"thread_id": "test-thread"}},
    )
    assert diff["faq_matches"] == []
    assert diff["history"] == []


async def test_retrieve_context_does_not_mutate_input(base_state: AgentState) -> None:
    snapshot = dict(base_state)
    await retrieve_context(base_state)
    assert dict(base_state) == snapshot


# ---------------------------------------------------------------------------
# Pool-path tests (mocked asyncpg + voyageai)
# ---------------------------------------------------------------------------


def _make_fake_pool(faq_rows: list, history_rows: list) -> MagicMock:
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[faq_rows, history_rows])

    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn_ctx)
    return pool


async def test_retrieve_context_maps_faq_rows_to_faq_match(
    base_state: AgentState,
) -> None:
    class FakeRow:
        def __getitem__(self, k):
            return {
                "id": "faq-1",
                "question": "Qual o horário?",
                "answer": "Das 9h às 18h.",
                "score": 0.91,
            }[k]

    pool = _make_fake_pool(faq_rows=[FakeRow()], history_rows=[])
    settings = get_settings()
    original_key = settings.voyage_api_key
    settings.voyage_api_key = "voy-test-key"

    _rc_mod._embed = AsyncMock(return_value=[0.1] * 512)
    try:
        diff = await retrieve_context(
            base_state,
            config={"configurable": {"thread_id": "t:c", "db_pool": pool}},
        )
    finally:
        del _rc_mod._embed
        settings.voyage_api_key = original_key

    assert len(diff["faq_matches"]) == 1
    match: FaqMatch = diff["faq_matches"][0]
    assert match["question"] == "Qual o horário?"
    assert match["score"] == pytest.approx(0.91)


async def test_retrieve_context_history_reversed_to_chronological(
    base_state: AgentState,
) -> None:
    class FakeRow:
        def __init__(self, role, content):
            self._d = {"role": role, "content": content}

        def __getitem__(self, k):
            return self._d[k]

    newest = FakeRow("assistant", "Posso ajudar!")
    oldest = FakeRow("user", "Ola")
    pool = _make_fake_pool(faq_rows=[], history_rows=[newest, oldest])

    settings = get_settings()
    original_key = settings.voyage_api_key
    settings.voyage_api_key = "voy-test-key"

    _rc_mod._embed = AsyncMock(return_value=[0.0] * 512)
    try:
        diff = await retrieve_context(
            base_state,
            config={"configurable": {"thread_id": "t:c", "db_pool": pool}},
        )
    finally:
        del _rc_mod._embed
        settings.voyage_api_key = original_key

    history = diff["history"]
    assert len(history) == 2
    # Node reverses DESC rows back to chronological (oldest first)
    assert history[0] == {"role": "user", "content": "Ola"}
    assert history[1] == {"role": "assistant", "content": "Posso ajudar!"}
