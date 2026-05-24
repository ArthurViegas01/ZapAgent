"""Circuit-breaker behavior of the rate-limit middleware.

These tests exercise the new fail-closed-after-N-errors path added on
2026-05-24. Without a circuit breaker, a sustained Redis outage left
the API in unbounded fail-open mode (effectively no rate limiting) —
fine for a 1-second blip, dangerous for a multi-hour outage.

The middleware's circuit-breaker state machine is pure logic plus a
``time.monotonic`` read, so we test it directly by invoking
``_check`` / ``_breaker_is_open`` on the middleware instance instead
of going through FastAPI's TestClient. Avoids the asyncio + ASGI
plumbing for what is at heart a deterministic counter test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core import rate_limit as rl
from src.core.rate_limit import RateLimitMiddleware


def _build_mw() -> RateLimitMiddleware:
    """Construct a middleware with a no-op ASGI app underneath."""

    async def _noop(scope, receive, send):
        return None

    return RateLimitMiddleware(_noop, redis_url="redis://unused-in-test")


def _failing_redis() -> MagicMock:
    """A Redis double whose pipeline.execute() always raises.

    pipe.incr / pipe.expire are sync calls in real redis-py (they only
    queue ops into the pipeline buffer); only execute() is async. Mock
    them as MagicMock to avoid unawaited-coroutine warnings.
    """
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=ConnectionError("simulated redis down"))
    redis.pipeline = lambda: pipe
    return redis


def _ok_redis(count: int = 1) -> MagicMock:
    """A Redis double that returns a successful INCR/EXPIRE result."""
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[count, True])
    redis.pipeline = lambda: pipe
    return redis


@pytest.mark.asyncio
async def test_single_redis_blip_does_not_trip_breaker() -> None:
    """One failure must not flip the breaker — that's why it's
    threshold-based, not single-shot. Below threshold the middleware
    stays in fail-open mode.
    """
    mw = _build_mw()
    mw._pool = _failing_redis()

    allowed, _ = await mw._check("k", 100, 60)

    assert allowed is True  # fail-open
    assert mw._consecutive_errors == 1
    assert mw._breaker_is_open() is False


@pytest.mark.asyncio
async def test_consecutive_failures_open_breaker() -> None:
    mw = _build_mw()
    mw._pool = _failing_redis()

    for _ in range(rl._BREAKER_THRESHOLD):
        await mw._check("k", 100, 60)

    assert mw._consecutive_errors == rl._BREAKER_THRESHOLD
    assert mw._breaker_is_open() is True


@pytest.mark.asyncio
async def test_success_resets_consecutive_error_counter() -> None:
    """Mixed success/failure must not accumulate — only *consecutive*
    failures matter. Otherwise a noisy day eventually trips the breaker
    on a healthy Redis, which is the wrong thing to do.
    """
    mw = _build_mw()

    # Two failures...
    mw._pool = _failing_redis()
    for _ in range(2):
        await mw._check("k", 100, 60)
    assert mw._consecutive_errors == 2

    # ...then a success resets the counter.
    mw._pool = _ok_redis(count=3)
    await mw._check("k", 100, 60)
    assert mw._consecutive_errors == 0
    assert mw._breaker_is_open() is False


@pytest.mark.asyncio
async def test_breaker_half_opens_after_cooldown() -> None:
    """Past the cooldown the breaker should allow the next call through
    (half-open state). A successful probe re-closes the circuit."""
    mw = _build_mw()
    mw._pool = _failing_redis()
    for _ in range(rl._BREAKER_THRESHOLD):
        await mw._check("k", 100, 60)
    assert mw._breaker_is_open() is True
    opened_at = mw._breaker_opened_at

    # Jump time past the cooldown window.
    with patch.object(
        rl.time,
        "monotonic",
        return_value=opened_at + rl._BREAKER_COOLDOWN_SECONDS + 0.1,
    ):
        assert mw._breaker_is_open() is False  # half-open
    # The half-open transition clears the opened_at marker.
    assert mw._breaker_opened_at == 0.0


@pytest.mark.asyncio
async def test_successful_probe_after_half_open_closes_circuit() -> None:
    mw = _build_mw()

    # Trip the breaker.
    mw._pool = _failing_redis()
    for _ in range(rl._BREAKER_THRESHOLD):
        await mw._check("k", 100, 60)
    opened_at = mw._breaker_opened_at

    # Cooldown elapses, Redis is back.
    mw._pool = _ok_redis(count=1)
    with patch.object(
        rl.time,
        "monotonic",
        return_value=opened_at + rl._BREAKER_COOLDOWN_SECONDS + 0.1,
    ):
        # is_open() triggers the half-open transition; the next _check
        # uses the (healthy) redis double and the success handler
        # zeroes the counter.
        assert mw._breaker_is_open() is False
        allowed, _ = await mw._check("k", 100, 60)
        assert allowed is True
    assert mw._consecutive_errors == 0
    assert mw._breaker_opened_at == 0.0


@pytest.mark.asyncio
async def test_breaker_threshold_is_off_by_one_safe() -> None:
    """Exactly _BREAKER_THRESHOLD-1 failures must NOT open the breaker.
    The boundary is the dangerous one; if it's wrong, we either flap on
    legitimate noise or never trip during an outage.
    """
    mw = _build_mw()
    mw._pool = _failing_redis()

    for _ in range(rl._BREAKER_THRESHOLD - 1):
        await mw._check("k", 100, 60)

    assert mw._breaker_is_open() is False
    # The Nth failure trips it.
    await mw._check("k", 100, 60)
    assert mw._breaker_is_open() is True
