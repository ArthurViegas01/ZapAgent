"""asyncpg connection pool factory.

FastAPI side: a single pool is created at startup (lifespan) and stored
in ``app.state.db_pool``. Lives for the process lifetime.

Celery side: pools are created **per task**, inside the task's
``asyncio.run()`` block, and closed when the task exits. Reusing a pool
across ``asyncio.run`` calls crashes with ``Event loop is closed``
because the pool's internal primitives are bound to the dead loop. See
``checkpointer.py`` for the same hazard and the same fix.

Usage in FastAPI:
    pool = request.app.state.db_pool

Usage in Celery tasks:
    async with worker_pool_scope() as pool:
        ...
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


async def create_pool() -> asyncpg.Pool:
    """Create and return a new asyncpg pool.

    Called by the FastAPI lifespan context (process-singleton) and by
    each Celery task (task-scoped via :func:`worker_pool_scope`).
    """
    settings = get_settings()
    # asyncpg needs the plain postgres:// URL (not the SQLAlchemy +psycopg one).
    url = settings.database_url_sync.replace(
        "postgresql://", "postgres://"
    )
    pool = await asyncpg.create_pool(
        dsn=url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    logger.info("db.pool.created")
    return pool


@asynccontextmanager
async def worker_pool_scope() -> AsyncIterator[asyncpg.Pool]:
    """Yield a pool scoped to the current event loop, then close it.

    Use this inside the ``_main`` of a Celery task so the pool's
    lifetime matches the task's ``asyncio.run`` loop. Cleanup runs even
    on exception via the context manager's ``finally``.
    """
    pool = await create_pool()
    try:
        yield pool
    finally:
        try:
            await pool.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("db.pool.close_failed", error=str(exc))
