"""Tenant-isolation guarantees, end-to-end against a real Postgres.

These three tests cover the three doors through which a multi-tenant
data leak could happen in Encaixe today:

1. ``test_rls_guc_isolates_faq_items``
   Proves Postgres RLS policies actually fire under a NOBYPASSRLS role,
   keyed by the connection-local GUC ``app.tenant_id``. This is the
   defense-in-depth ARCHITECTURE.md §2.4 promises for the FastAPI path
   (``dependencies.require_tenant`` sets the GUC on every request).

2. ``test_retrieve_context_query_faq_isolates_tenants``
   Calls the production helper ``retrieve_context._query_faq`` with two
   tenants and a fixed embedding. Asserts the rows returned belong only
   to the requested tenant. Catches regressions in the WHERE clause or
   the GUC SET LOCAL inside that function.

3. ``test_resolve_tenant_by_instance_name``
   Calls the production helper ``webhooks.whatsapp._resolve_tenant`` for
   each tenant's WhatsApp instance name. Catches a regression where an
   instance lookup returns the wrong tenant (which would route inbound
   messages to the wrong account).

Marker
------
All tests carry ``@pytest.mark.integration``. The CI workflow opts in via
``pytest -m integration`` after the unit suite. Local devs run them with
``make test-integration`` once docker-compose is up.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


# ---------------------------------------------------------------------------
# 1. RLS via GUC actually isolates rows under a NOBYPASSRLS role
# ---------------------------------------------------------------------------


async def test_rls_guc_isolates_faq_items(integration_pool, two_tenants):
    """With role app_user_test, SET LOCAL app.tenant_id = A ⇒ only A's rows.

    Three sub-assertions in one test because they share fixture work:
      - GUC = A returns only A's 2 FAQ rows
      - GUC = B returns only B's 2 FAQ rows
      - No GUC returns 0 rows (RLS rejects the read)
    """
    async with integration_pool.acquire() as conn, conn.transaction():
        # Switch to the low-privilege role for this transaction only.
        await conn.execute("SET LOCAL ROLE app_user_test")

        # -- GUC = A ----------------------------------------------
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(two_tenants["a_id"]))
        rows_a = await conn.fetch("SELECT tenant_id FROM faq_items")
        assert len(rows_a) == 2, (
            "expected exactly the 2 FAQ rows seeded for tenant A, "
            f"got {len(rows_a)} — RLS may be bypassed or policy missing"
        )
        assert all(r["tenant_id"] == two_tenants["a_id"] for r in rows_a)

        # -- GUC = B ----------------------------------------------
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(two_tenants["b_id"]))
        rows_b = await conn.fetch("SELECT tenant_id FROM faq_items")
        assert len(rows_b) == 2
        assert all(r["tenant_id"] == two_tenants["b_id"] for r in rows_b)

        # -- No GUC set: current_tenant_id() returns NULL ---------
        await conn.execute("SELECT set_config('app.tenant_id', '', true)")
        rows_none = await conn.fetch("SELECT tenant_id FROM faq_items")
        assert rows_none == [], (
            "expected zero rows when app.tenant_id is unset — "
            "tenant_isolation policy may have a faulty USING clause"
        )


# ---------------------------------------------------------------------------
# 2. The actual helper used by the agent isolates tenants
# ---------------------------------------------------------------------------


async def test_retrieve_context_query_faq_isolates_tenants(integration_pool, two_tenants):
    """``_query_faq`` is the FAQ retrieval call inside ``retrieve_context``.

    We bypass the embedding step (which would require a Voyage AI key)
    and supply a vector matching the seeded embedding directly, so
    cosine distance ≈ 0 and both seeded rows per tenant land in top-k.
    The point of the test is isolation, not ranking quality.
    """
    from src.agent.nodes.retrieve_context import _query_faq, _vec_literal

    # Match the fixture's seeded vector so cosine distance is ~0 and
    # the seeded rows land in top-k.
    query_vec = _vec_literal([0.01] * 1024)

    matches_a = await _query_faq(
        integration_pool,
        tenant_id=str(two_tenants["a_id"]),
        vec_lit=query_vec,
        top_k=10,
    )
    matches_b = await _query_faq(
        integration_pool,
        tenant_id=str(two_tenants["b_id"]),
        vec_lit=query_vec,
        top_k=10,
    )

    # Hard count: exactly the 2 rows we seeded per tenant. Anything else
    # means the WHERE tenant_id filter slipped or the seed is wrong.
    assert len(matches_a) == 2, f"tenant A expected 2 FAQ matches, got {len(matches_a)}"
    assert len(matches_b) == 2, f"tenant B expected 2 FAQ matches, got {len(matches_b)}"

    a_ids = {m["id"] for m in matches_a}
    b_ids = {m["id"] for m in matches_b}
    assert not (a_ids & b_ids), (
        f"FAQ retrieval leaked rows across tenants — overlap: {sorted(a_ids & b_ids)}"
    )

    # Every returned question must belong to the requested tenant. We
    # have distinct text per tenant in the fixture (Horario A? vs B?).
    for m in matches_a:
        assert m["question"].endswith("A?"), f"tenant A retrieval returned a non-A row: {m}"
    for m in matches_b:
        assert m["question"].endswith("B?"), f"tenant B retrieval returned a non-B row: {m}"


# ---------------------------------------------------------------------------
# 3. Webhook tenant resolution doesn't mix instances
# ---------------------------------------------------------------------------


async def test_resolve_tenant_by_instance_name(integration_pool, two_tenants):
    """``webhooks.whatsapp._resolve_tenant`` maps instance → tenant cleanly."""
    from src.api.webhooks.whatsapp import _resolve_tenant

    async with integration_pool.acquire() as conn:
        a_resolved = await _resolve_tenant(conn, two_tenants["a_instance"])
        b_resolved = await _resolve_tenant(conn, two_tenants["b_instance"])
        unknown = await _resolve_tenant(conn, "instance-that-does-not-exist")

    assert a_resolved == str(two_tenants["a_id"])
    assert b_resolved == str(two_tenants["b_id"])
    assert unknown is None, (
        "expected None for an unknown instance — anything else means an "
        "inbound webhook could be attributed to the wrong tenant"
    )
