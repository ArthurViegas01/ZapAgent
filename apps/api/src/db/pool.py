"""asyncpg connection pool factory.

A single pool is created at API startup and stored in `app.state.db_pool`.
The Celery worker creates its own pool lazily (one per worker process).

Usage in FastAPI:
    pool = request.app.state.db_pool

Usage in Celery tasks:
    pool = await get_worker_pool()
"""

from __future__ import annotations

import asyncpg

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Celery worker: one pool per process, created on first use.
_worker_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    """Create and return a new asyncpg pool.

    Called once at FastAPI startup via the lifespan context manager.
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


async def get_worker_pool() -> asyncpg.Pool:
    """Return the Celery worker pool, creating it on first call per process."""
    global _worker_pool
    if _worker_pool is None:
        _worker_pool = await create_pool()
    return _worker_pool
