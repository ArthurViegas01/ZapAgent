"""Unit tests for the subscription gate.

We mock the asyncpg pool with a MagicMock that supports the
``async with pool.acquire() as conn`` protocol — same pattern as
``tests/test_webhook_whatsapp.py``. This keeps the test suite fast and
avoids dragging in the integration fixture for every billing change.

Coverage matrix:

  status      | trial_ends_at  | expected
  ------------|----------------|-----------------
  active      | (anything)     | allowed=True
  past_due    | (anything)     | allowed=True  (grace)
  suspended   | (anything)     | allowed=False, reason=suspended
  trialing    | future         | allowed=True, days_left>0
  trialing    | past           | allowed=False, reason=trial_expired
  trialing    | NULL           | allowed=True, reason=trialing_no_end (warn)
  (no tenant) | -              | allowed=False, reason=tenant_not_found
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.billing_gate import check_subscription


def _mock_pool_returning(row: dict | None) -> MagicMock:
    """Build an asyncpg.Pool double that returns ``row`` from fetchrow.

    The two async context managers (pool.acquire and conn.transaction)
    are emulated with AsyncMock + __aenter__/__aexit__ so the production
    helper sees a pool that behaves like the real thing.
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


TID = "00000000-0000-0000-0000-000000000abc"


@pytest.mark.asyncio
async def test_active_subscription_is_allowed():
    pool = _mock_pool_returning({"subscription_status": "active", "trial_ends_at": None})
    result = await check_subscription(pool, TID)
    assert result.allowed is True
    assert result.status == "active"
    assert result.reply_to_customer == ""
    assert result.reason == "active"


@pytest.mark.asyncio
async def test_past_due_is_allowed_grace_period():
    pool = _mock_pool_returning({"subscription_status": "past_due", "trial_ends_at": None})
    result = await check_subscription(pool, TID)
    assert result.allowed is True
    assert result.reason == "past_due_grace"


@pytest.mark.asyncio
async def test_suspended_is_blocked_with_pause_message():
    pool = _mock_pool_returning({"subscription_status": "suspended", "trial_ends_at": None})
    result = await check_subscription(pool, TID)
    assert result.allowed is False
    assert result.status == "suspended"
    assert "pausado" in result.reply_to_customer.lower()
    assert result.reason == "suspended"


@pytest.mark.asyncio
async def test_trialing_with_future_end_is_allowed_with_days_left():
    future = datetime.now(tz=UTC) + timedelta(days=7, hours=2)
    pool = _mock_pool_returning({"subscription_status": "trialing", "trial_ends_at": future})
    result = await check_subscription(pool, TID)
    assert result.allowed is True
    assert result.status == "trialing"
    assert result.days_left == 7  # timedelta.days truncates


@pytest.mark.asyncio
async def test_trialing_with_past_end_is_blocked():
    past = datetime.now(tz=UTC) - timedelta(minutes=1)
    pool = _mock_pool_returning({"subscription_status": "trialing", "trial_ends_at": past})
    result = await check_subscription(pool, TID)
    assert result.allowed is False
    assert result.status == "trialing"
    assert result.days_left == 0
    assert "teste" in result.reply_to_customer.lower()
    assert result.reason == "trial_expired"


@pytest.mark.asyncio
async def test_trialing_with_null_end_is_allowed_but_flagged():
    pool = _mock_pool_returning({"subscription_status": "trialing", "trial_ends_at": None})
    result = await check_subscription(pool, TID)
    assert result.allowed is True
    assert result.reason == "trialing_no_end"


@pytest.mark.asyncio
async def test_unknown_tenant_is_blocked():
    pool = _mock_pool_returning(None)
    result = await check_subscription(pool, TID)
    assert result.allowed is False
    assert result.status == "unknown"
    assert result.reason == "tenant_not_found"
