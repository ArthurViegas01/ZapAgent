"""LangGraph checkpointer wiring.

ARCHITECTURE.md §2.5 promised a ``PostgresSaver`` backed by the same DB
the rest of the app uses, with ``thread_id = "{tenant_id}:{conversation_id}"``
so a conversation survives worker restarts. The agent pipeline however
booted with ``MemorySaver`` in production — every container restart blew
away in-flight conversation state, which is fine for unit tests but
unacceptable for a paying customer mid-conversation.

This module fills that gap.

Lifecycle: per-task, not process-singleton
------------------------------------------
Celery prefork workers run each task via ``asyncio.run(_main())``, which
creates a fresh event loop per task and tears it down at exit. Any
asyncio primitive (``Lock``, ``Pool``, ``Connection``) created in loop
A and reused in loop B raises ``RuntimeError: ... is bound to a
different event loop`` — a real production crash we hit on 2026-05-24.

We therefore open the psycopg pool and the saver **inside each task**
and close them in a ``finally`` block. The TCP-connect cost (~50 ms to
Supabase pooler) is negligible compared to the multi-second LLM call
that dominates each turn. A future migration to a persistent worker
event loop (``--pool=gevent``, or a background-thread loop) would
restore process-level pooling without the event-loop hazard.

Why a separate psycopg pool (not the asyncpg one)
-------------------------------------------------
``langgraph-checkpoint-postgres`` is built on top of ``psycopg`` (not
``asyncpg``). Trying to thread asyncpg connections through it requires
adapter glue that buys us nothing.

Idempotent setup
----------------
``saver.setup()`` creates its own tables (``checkpoints``,
``checkpoint_blobs``, ``checkpoint_writes``, ``checkpoint_migrations``)
on first use. ``IF NOT EXISTS`` makes repeat calls cheap, but we still
prefer not to run the DDL every task — see :func:`get_async_postgres_saver`
for the per-process ``_setup_done_for_dsn`` cache.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Setup-DDL guard. The saver's setup() runs CREATE TABLE IF NOT EXISTS
# statements — safe to repeat, but cheap to skip after the first task in
# the process has done it. Storing the DSN (not just a bool) avoids
# accidentally skipping setup if the DSN is rotated mid-process.
_setup_done_for_dsn: str | None = None


def _psycopg_dsn() -> str:
    """Convert the SQLAlchemy-style URL in settings to a libpq DSN.

    psycopg understands ``postgresql://`` and ``postgres://`` natively;
    it does not understand the SQLAlchemy ``postgresql+psycopg://``
    prefix, so we strip the driver tag if present.
    """
    settings = get_settings()
    dsn = settings.database_url_sync or str(settings.database_url)
    return dsn.replace("postgresql+psycopg://", "postgresql://")


@asynccontextmanager
async def async_postgres_saver_scope() -> AsyncIterator[Any]:
    """Yield a fresh ``AsyncPostgresSaver`` bound to the current event loop.

    Opens a small psycopg ``AsyncConnectionPool`` for the duration of the
    context and closes it on exit. Safe to call from any event loop —
    including a fresh one inside ``asyncio.run`` — because no state
    leaks across loops.

    The DDL ``setup()`` runs only once per (process, DSN) tuple.
    """
    global _setup_done_for_dsn

    # Lazy imports keep the module import side-effect-free.
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    dsn = _psycopg_dsn()
    pool = AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        # Saver opens short transactions; autocommit reduces locking
        # surface and matches the saver's own factory.
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool)
        if _setup_done_for_dsn != dsn:
            await saver.setup()
            _setup_done_for_dsn = dsn
            logger.info("checkpointer.setup_done")
        yield saver
    finally:
        try:
            await pool.close()
        except Exception as exc:
            logger.warning("checkpointer.pool_close_failed", error=str(exc))


async def get_async_postgres_saver() -> Any:
    """Deprecated process-singleton accessor.

    Retained for callers that haven't migrated to
    :func:`async_postgres_saver_scope`. Each call opens a *fresh* pool
    and saver and never closes them — the loop's exit cleans up via GC.
    Do **not** use from Celery tasks (use the context manager instead).
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    global _setup_done_for_dsn
    dsn = _psycopg_dsn()
    pool = AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(conn=pool)
    if _setup_done_for_dsn != dsn:
        await saver.setup()
        _setup_done_for_dsn = dsn
    return saver
