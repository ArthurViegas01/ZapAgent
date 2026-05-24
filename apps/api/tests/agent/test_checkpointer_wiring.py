"""Smoke tests for the PostgresSaver wiring.

The full durability proof (kill worker mid-conversation, restart, resume)
is an integration test that needs a real Celery worker + Postgres. Here
we cover the cheap invariants:

  * ``build_graph`` accepts a custom checkpointer and uses it.
  * The fallback path in ``_run_agent`` activates when the saver init
    raises, and the graph still completes via MemorySaver.

We don't import ``checkpointer.get_async_postgres_saver`` here on purpose
— it would pull in psycopg and a real DSN. That path is exercised in
``tests/integration/`` once the saver tables exist.
"""

from __future__ import annotations

import pytest


def test_build_graph_accepts_custom_checkpointer():
    """If we pass a checkpointer, build_graph must use it (not MemorySaver)."""
    from langgraph.checkpoint.memory import MemorySaver

    from src.agent.graph import build_graph

    custom = MemorySaver()
    graph = build_graph(checkpointer=custom)
    # langgraph stores the checkpointer on the compiled graph object.
    # Direct attribute name has shifted across versions; the public
    # contract is that two separately-built graphs with distinct savers
    # don't share state. Validate by identity on `checkpointer` if the
    # attr exists, otherwise by behaviour below.
    assert hasattr(graph, "checkpointer")
    assert graph.checkpointer is custom


def test_build_graph_defaults_to_memory_saver_when_none():
    from langgraph.checkpoint.memory import MemorySaver

    from src.agent.graph import build_graph

    graph = build_graph(checkpointer=None)
    assert isinstance(graph.checkpointer, MemorySaver)


@pytest.mark.asyncio
async def test_run_agent_falls_back_when_saver_init_fails(monkeypatch):
    """If get_async_postgres_saver() raises, _run_agent must still produce
    a final state instead of crashing the Celery task."""
    import src.worker.tasks as tasks_module

    # Make the saver init blow up. The function is imported inside
    # _run_agent so we patch the module the import resolves to.
    from src.agent import checkpointer as ck_mod

    async def _boom() -> object:
        raise RuntimeError("simulated saver init failure")

    monkeypatch.setattr(ck_mod, "get_async_postgres_saver", _boom)

    # _run_agent expects a "pool". Pass None — retrieve_context handles
    # the no-pool case by returning empty stubs, and the rest of the
    # graph runs offline because conftest cleared anthropic_api_key.
    result = await tasks_module._run_agent(
        tenant_id="00000000-0000-0000-0000-000000000099",
        conversation_id="11111111-1111-1111-1111-111111111199",
        contact_phone="5511999999999",
        user_message="oi",
        tenant_settings={},
        pool=None,
    )
    assert isinstance(result, dict)
    # response is filled by either generate_response or handoff_human;
    # both paths yield a string. The exact text depends on the offline
    # fallback in generate_response.py.
    assert "response" in result
