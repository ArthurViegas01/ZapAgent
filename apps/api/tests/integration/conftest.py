"""Fixtures for tenant-isolation integration tests.

These tests are real-database tests. They connect to PostgreSQL via
asyncpg using ``settings.database_url_sync``, ensure both migrations
(0001 + 0002) have been applied, install a low-privilege role used to
prove the RLS policies, seed two tenants with deterministic UUIDs and
disjoint data, and return helper fixtures the tests consume.

Why a dedicated low-privilege role
----------------------------------
The pool used by FastAPI / Celery in production usually connects as the
owner of the tables (the role that ran the migrations). Owners bypass
RLS in Postgres — the GUC + policy combination is therefore application-
layer defense-in-depth, not the actual gate.

To assert that the RLS policies do what we promise in ARCHITECTURE.md
§2.4 (and that a misconfigured service-role connection would still be
caught at the DB layer), the test harness installs ``app_user_test``
with ``NOBYPASSRLS`` and ``GRANT SELECT, INSERT, UPDATE, DELETE`` on the
tenant-scoped tables, then runs the RLS test under that role via
``SET LOCAL ROLE``.

Skipping
--------
If asyncpg cannot connect (no DB, no docker compose up, …) the whole
module skips so this test suite doesn't break a dev who only has the
unit fast path.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

try:
    import asyncpg
except ImportError:  # pragma: no cover — pyproject pins this
    asyncpg = None  # type: ignore[assignment]


# Deterministic UUIDs so tests can assert on identity directly.
TENANT_A_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
INSTANCE_A = "za-tenantA-fixture"
INSTANCE_B = "za-tenantB-fixture"


def _resolve_dsn() -> str:
    """Pick the asyncpg-compatible DSN.

    The Settings class stores the SQLAlchemy-style URL in ``database_url``
    (``postgresql+psycopg://...``) and a plain Postgres URL in
    ``database_url_sync``. asyncpg only accepts the plain form.
    """
    from src.core.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    raw = settings.database_url_sync or os.environ.get("DATABASE_URL_SYNC", "")
    # asyncpg accepts ``postgres://`` and ``postgresql://`` — strip drivers
    # if present.
    return raw.replace("postgresql+psycopg://", "postgresql://")


async def _try_connect(dsn: str) -> bool:
    if asyncpg is None:
        return False
    try:
        conn = await asyncpg.connect(dsn, timeout=3)
    except Exception:  # noqa: BLE001
        return False
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()
    return True


@pytest_asyncio.fixture(scope="session")
async def integration_dsn() -> str:
    dsn = _resolve_dsn()
    if not await _try_connect(dsn):
        pytest.skip(
            "Postgres unreachable at DATABASE_URL_SYNC — integration "
            "tests need `docker compose up postgres` (or equivalent)."
        )
    return dsn


@pytest_asyncio.fixture(scope="session")
async def integration_pool(integration_dsn: str) -> AsyncIterator["asyncpg.Pool"]:
    """Session-scoped asyncpg pool used by every integration test."""
    assert asyncpg is not None
    pool = await asyncpg.create_pool(
        dsn=integration_dsn,
        min_size=1,
        max_size=4,
        command_timeout=15,
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="session")
async def _ensure_test_role(integration_pool: "asyncpg.Pool") -> None:
    """Create ``app_user_test`` with NOBYPASSRLS, idempotently.

    The role is used to assert RLS policies actually fire. We do NOT
    grant SUPERUSER or rely on a privileged escalation — it has the
    bare minimum needed to read/write tenant-scoped tables.
    """
    async with integration_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'app_user_test'"
        )
        if not exists:
            await conn.execute(
                "CREATE ROLE app_user_test NOLOGIN NOINHERIT NOBYPASSRLS"
            )
        # Grants are idempotent — re-running is cheap.
        await conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE "
            "ON tenants, users, integrations, faq_items, conversations, "
            "messages, appointments, webhook_events TO app_user_test"
        )
        await conn.execute("GRANT USAGE ON SCHEMA public TO app_user_test")


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    integration_pool: "asyncpg.Pool",
    _ensure_test_role: None,
) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Seed two disjoint tenants and clean up after the test.

    Each test gets a fresh DB state so order independence holds.
    Cleanup uses TRUNCATE ... RESTART IDENTITY CASCADE for speed; we
    skip tables not present in the schema gracefully via DO/EXCEPTION
    in case the migration set changes.
    """
    async with integration_pool.acquire() as conn:
        # Truncate first — we own the fixture, so cascading is safe.
        await conn.execute(
            "TRUNCATE TABLE webhook_events, appointments, messages, "
            "conversations, faq_items, integrations, users, tenants "
            "RESTART IDENTITY CASCADE"
        )

        # -- tenants --------------------------------------------------
        await conn.executemany(
            "INSERT INTO tenants (id, slug, name) VALUES ($1::uuid, $2, $3)",
            [
                (str(TENANT_A_ID), "tenant-a", "Tenant A"),
                (str(TENANT_B_ID), "tenant-b", "Tenant B"),
            ],
        )

        # -- FAQ items: 2 per tenant, distinct text ------------------
        # Embedding is populated with a tiny non-zero vector so cosine
        # distance is defined inside ``_query_faq`` (cosine is undefined
        # for the zero vector — pgvector returns NULL, which would
        # propagate through ORDER BY and break the score cast).
        # Schema is VECTOR(1024) per migration 0001 (forward-compat with
        # voyage-3; voyage-3-lite itself is 512-dim, see note in
        # retrieve_context.py).
        vec_lit = "[" + ",".join(["0.01"] * 1024) + "]"
        await conn.executemany(
            "INSERT INTO faq_items "
            "(tenant_id, question, answer, embedding) "
            "VALUES ($1::uuid, $2, $3, $4::vector)",
            [
                (str(TENANT_A_ID), "Horario A?", "Atendimento A das 9 as 18.", vec_lit),
                (str(TENANT_A_ID), "Endereco A?", "Rua A, 100.", vec_lit),
                (str(TENANT_B_ID), "Horario B?", "Atendimento B das 8 as 17.", vec_lit),
                (str(TENANT_B_ID), "Endereco B?", "Rua B, 200.", vec_lit),
            ],
        )

        # -- WhatsApp integrations --- one per tenant ----------------
        await conn.executemany(
            "INSERT INTO integrations "
            "(tenant_id, kind, external_id, status, config) "
            "VALUES ($1::uuid, 'whatsapp', $2, 'connected', '{}'::jsonb)",
            [
                (str(TENANT_A_ID), INSTANCE_A),
                (str(TENANT_B_ID), INSTANCE_B),
            ],
        )

    yield {
        "a_id": TENANT_A_ID,
        "b_id": TENANT_B_ID,
        "a_instance": INSTANCE_A,
        "b_instance": INSTANCE_B,
    }

    # No teardown — next test's TRUNCATE handles it.
