"""LangGraph checkpointer wiring.

ARCHITECTURE.md §2.5 promised a ``PostgresSaver`` backed by the same DB
the rest of the app uses, with ``thread_id = "{tenant_id}:{conversation_id}"``
so a conversation survives worker restarts. The agent pipeline however
booted with ``MemorySaver`` in production — every container restart blew
away in-flight conversation state, which is fine for unit tests but
unacceptable for a paying customer mid-conversation.

This module fills that gap.

Two implementations
-------------------
* **API path** (FastAPI request → in-process graph invocation, rare) —
  uses the async saver. Not currently used; the path of record is the
  worker.
* **Worker path** (Celery task → graph invocation) — uses the async
  saver too. Every Celery task opens its own ``asyncio.run()`` so the
  saver lives for the duration of that loop. We keep a process-level
  connection pool to amortize the TCP cost across tasks.

Why a separate psycopg pool (not the asyncpg one)
-------------------------------------------------
``langgraph-checkpoint-postgres`` is built on top of ``psycopg`` (not
``asyncpg``). Trying to thread asyncpg connections through it requires
adapter glue that buys us nothing — the cost of a second pool with a
small ``max_size`` is negligible compared to the LLM calls dominating
each request.

Idempotent setup
----------------
The saver creates its own tables (``checkpoints``, ``checkpoint_blobs``,
``checkpoint_writes``, ``checkpoint_migrations``) on first use. We call
``setup()`` exactly once per process, guarded by a lock so concurrent
Celery tasks don't race the first invocation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Process-level state. Lazy-initialized on first call; rest of the
# process reuses the same saver+pool combination.
_pool: Any = None  # psycopg AsyncConnectionPool when initialized
_saver: Any = None  # AsyncPostgresSaver when initialized
_setup_done: bool = False
_init_lock = asyncio.Lock()


def _psycopg_dsn() -> str:
    """Convert the SQLAlchemy-style URL in settings to a libpq DSN.

    psycopg understands ``postgresql://`` and ``postgres://`` natively;
    it does not understand the SQLAlchemy ``postgresql+psycopg://``
    prefix, so we strip the driver tag if present.
    """
    settings = get_settings()
    dsn = settings.database_url_sync or str(settings.database_url)
    return dsn.replace("postgresql+psycopg://", "postgresql://")


async def get_async_postgres_saver() -> Any:
    """Return a process-singleton ``AsyncPostgresSaver``.

    On first call, opens a small psycopg ``AsyncConnectionPool`` and
    runs the saver's ``setup()`` so the checkpoint tables exist. Both
    are idempotent — subsequent calls return the cached saver.

    Raises:
        ImportError: if ``langgraph-checkpoint-postgres`` is not
            installed (it is pinned in pyproject; this would indicate a
            broken environment, not a user error).
    """
    global _pool, _saver, _setup_done

    if _saver is not None and _setup_done:
        return _saver

    async with _init_lock:
        if _saver is not None and _setup_done:
            return _saver

        # Lazy imports keep the module import side-effect-free, which
        # matters for unit tests that build the graph with MemorySaver
        # and never need psycopg at all.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: PLC0415
        from psycopg_pool import AsyncConnectionPool  # noqa: PLC0415

        if _pool is None:
            _pool = AsyncConnectionPool(
                conninfo=_psycopg_dsn(),
                min_size=1,
                max_size=4,
                # Saver opens short transactions; autocommit reduces
                # locking surface and matches the saver's own assumptions
                # in its ``from_conn_string`` factory.
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,
            )
            await _pool.open()
            logger.info("checkpointer.pool_opened", min_size=1, max_size=4)

        if _saver is None:
            _saver = AsyncPostgresSaver(conn=_pool)

        if not _setup_done:
            await _saver.setup()
            _setup_done = True
            logger.info("checkpointer.setup_done")

    return _saver


async def close_async_postgres_saver() -> None:
    """Tear down the saver and its pool — for graceful shutdown or tests."""
    global _pool, _saver, _setup_done
    if _pool is not None:
        try:
            await _pool.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("checkpointer.pool_close_failed", error=str(exc))
    _pool = None
    _saver = None
    _setup_done = False
