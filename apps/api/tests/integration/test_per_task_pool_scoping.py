"""Regression for the 2026-05-24 per-task pool scoping fix.

Background
----------
Celery prefork workers run each task via ``asyncio.run(_main())`` — a
fresh event loop per task. Before commit 4d6d9be the worker's asyncpg
pool and the LangGraph PostgresSaver were process-level singletons; the
second task in a worker process crashed with::

    RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop

because the pool's internal locks were created in task A's (now dead)
loop. The fix moved both to per-task ``@asynccontextmanager`` scopes
(:func:`worker_pool_scope`, :func:`async_postgres_saver_scope`).

What this test guards
---------------------
Two consecutive ``asyncio.run()`` calls in the same process must both
succeed when wrapped in the scope context managers. If a future
refactor reintroduces a process-singleton pool/lock/saver, the second
``asyncio.run`` here will crash with the original "bound to a different
event loop" error.

Skipped when Postgres is unreachable so the unit-test fast path still
works (see ``integration_dsn`` fixture).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration


async def _trivial_pool_use() -> int:
    """Open a worker_pool_scope, run SELECT 1, close it. Exercises every
    asyncio primitive that was previously leaking across loops."""
    from src.db.pool import worker_pool_scope

    async with worker_pool_scope() as pool, pool.acquire() as conn:
        value: int = await conn.fetchval("SELECT 1")
    return value


async def _trivial_saver_use() -> bool:
    """Open the AsyncPostgresSaver scope and let setup() run (idempotent
    after first task per process). The internal psycopg AsyncConnection-
    Pool is the primitive that crashed pre-fix.
    """
    from src.agent.checkpointer import async_postgres_saver_scope

    async with async_postgres_saver_scope() as saver:
        # Touching .conn forces the pool to be alive; we don't need a
        # real checkpoint write to assert non-crashing behavior.
        return saver is not None


def test_two_consecutive_asyncio_runs_share_no_state(integration_dsn: str) -> None:
    """Two ``asyncio.run`` calls back-to-back in the same process must
    both succeed. This reproduces the Celery prefork task lifecycle.

    The fixture is requested only so the test skips cleanly when
    Postgres is unreachable; the DSN string itself is unused (settings
    point at it already).
    """
    del integration_dsn  # only used to gate the skip via the fixture
    first = asyncio.run(_trivial_pool_use())
    second = asyncio.run(_trivial_pool_use())
    assert first == 1
    assert second == 1


def test_two_consecutive_saver_scopes_do_not_leak_loop_state(
    integration_dsn: str,
) -> None:
    """Same shape as above but for the LangGraph PostgresSaver scope.
    Before the fix, the module-level ``_init_lock = asyncio.Lock()``
    bound to task A's loop blew up at saver-acquire in task B.
    """
    del integration_dsn
    assert asyncio.run(_trivial_saver_use()) is True
    assert asyncio.run(_trivial_saver_use()) is True
