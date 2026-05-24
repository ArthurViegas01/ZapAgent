"""Redis-based sliding-window rate limiter for FastAPI.

Strategy:
  - Authenticated routes:  120 requests / 60 s  per tenant_id
  - Unauthenticated routes: 30 requests / 60 s  per client IP
  - Exempt paths: /health, /webhooks/ (Evolution sends bursts of events)

Implementation uses Redis INCR + EXPIRE (atomic enough for our SLA).

Circuit breaker (Redis failure handling)
----------------------------------------
The default behavior is fail-open: a single Redis hiccup must not cause
a customer-visible 429 storm. But unbounded fail-open is also a foot-gun
— if Redis stays down for hours, the service is effectively running with
no rate limiting at all, and a bot sweep can hammer Anthropic/Voyage
quota dry on our dime.

After ``_BREAKER_THRESHOLD`` consecutive Redis errors we flip the breaker
*open* (in the electrical sense: circuit broken). While open, every
request is rejected with HTTP 503 ``rate_limit_unavailable`` instead of
falling through to the agent. The breaker stays open for
``_BREAKER_COOLDOWN_SECONDS`` before allowing a single probe; a
successful probe closes the circuit and resets the counter.

This is intentionally a *fail-closed-after-N* behavior, not pure
fail-closed: a one-off network blip never trips it, but a real outage
(N consecutive failures) does, and clients get a clear retry signal
instead of silent degradation.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .logging import get_logger

logger = get_logger(__name__)

# Paths that bypass rate limiting entirely.
_EXEMPT_PREFIXES = ("/health", "/webhooks/", "/docs", "/openapi")

# Per-tenant limit (authenticated requests).
_TENANT_LIMIT = 120
_TENANT_WINDOW = 60  # seconds

# Per-IP limit (unauthenticated requests).
_IP_LIMIT = 30
_IP_WINDOW = 60  # seconds

# Circuit-breaker thresholds. Tuned for "transient blip vs sustained
# outage": 5 consecutive failures is well above the noise floor for
# managed Redis (Railway's redis plugin has occasional 1-tick blips)
# but well below the volume needed for an attacker to exploit fail-open.
# 30 s cooldown matches the longest natural Redis failover window.
_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_SECONDS = 30.0


def _extract_tenant_from_bearer(authorization: str) -> str | None:
    """Quick unverified claim extraction — rate key only, not auth."""
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    try:
        from jose import jwt

        claims = jwt.get_unverified_claims(token)
        return claims.get("app_metadata", {}).get("tenant_id") or claims.get("sub") or None
    except Exception:
        return None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-tenant and per-IP rate limits."""

    def __init__(self, app: Callable, redis_url: str) -> None:
        super().__init__(app)
        self._redis_url = redis_url
        self._pool: aioredis.Redis | None = None
        # Circuit-breaker state. _consecutive_errors counts blips since
        # the last success; _breaker_opened_at is the wall clock at the
        # moment the breaker tripped (0 = closed).
        self._consecutive_errors = 0
        self._breaker_opened_at: float = 0.0

    async def _get_redis(self) -> aioredis.Redis | None:
        if self._pool is None:
            try:
                self._pool = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=1,
                )
            except Exception as exc:
                logger.warning("rate_limit.redis_connect_failed", error=str(exc))
        return self._pool

    def _breaker_is_open(self) -> bool:
        """Return True iff we're currently in the open-circuit window.

        The breaker auto-closes when the cooldown expires; the next
        successful Redis call resets the counter via :meth:`_on_success`.
        """
        if self._breaker_opened_at == 0.0:
            return False
        if time.monotonic() - self._breaker_opened_at >= _BREAKER_COOLDOWN_SECONDS:
            # Cooldown elapsed: allow a probe through; if it fails we'll
            # re-trip below. Logging the half-open transition makes it
            # easy to spot in Sentry / log search.
            logger.info("rate_limit.breaker_half_open")
            self._breaker_opened_at = 0.0
            return False
        return True

    def _on_success(self) -> None:
        if self._consecutive_errors > 0 or self._breaker_opened_at != 0.0:
            logger.info(
                "rate_limit.breaker_closed",
                consecutive_errors_before=self._consecutive_errors,
            )
        self._consecutive_errors = 0
        self._breaker_opened_at = 0.0

    def _on_failure(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= _BREAKER_THRESHOLD and self._breaker_opened_at == 0.0:
            self._breaker_opened_at = time.monotonic()
            logger.warning(
                "rate_limit.breaker_opened",
                consecutive_errors=self._consecutive_errors,
                cooldown_seconds=_BREAKER_COOLDOWN_SECONDS,
            )

    async def _check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Increment counter. Returns (allowed, requests_remaining).

        Returns ``(False, 0)`` only when Redis says the bucket is full.
        Redis-unreachable cases return ``(True, limit)`` (fail-open),
        but each unreachable call advances the circuit-breaker counter;
        once tripped, the caller (``dispatch``) short-circuits to 503
        without entering this method.
        """
        redis = await self._get_redis()
        if redis is None:
            self._on_failure()
            return True, limit  # fail open (until breaker trips)

        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)
            results = await pipe.execute()
            count: int = results[0]
            remaining = max(0, limit - count)
            self._on_success()
            return count <= limit, remaining
        except Exception as exc:
            logger.warning("rate_limit.redis_error", error=str(exc))
            self._on_failure()
            return True, limit  # fail open (until breaker trips)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip exempt paths.
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Circuit breaker: short-circuit to 503 without touching Redis if
        # the breaker is open. Webhooks bypass this via _EXEMPT_PREFIXES
        # above so a Redis outage never drops inbound WhatsApp events.
        if self._breaker_is_open():
            logger.warning("rate_limit.breaker_open_reject", path=path)
            return JSONResponse(
                status_code=503,
                content={"detail": ("Rate limiter temporarily unavailable. Please retry shortly.")},
                headers={"Retry-After": str(int(_BREAKER_COOLDOWN_SECONDS))},
            )

        # Determine rate-limit key and window.
        auth_header = request.headers.get("authorization", "")
        tenant_id = _extract_tenant_from_bearer(auth_header) if auth_header else None

        if tenant_id:
            bucket = int(time.time()) // _TENANT_WINDOW
            key = f"rl:t:{tenant_id}:{bucket}"
            limit, window = _TENANT_LIMIT, _TENANT_WINDOW
        else:
            ip = _client_ip(request)
            bucket = int(time.time()) // _IP_WINDOW
            key = f"rl:ip:{ip}:{bucket}"
            limit, window = _IP_LIMIT, _IP_WINDOW

        allowed, remaining = await self._check(key, limit, window)

        if not allowed:
            logger.warning(
                "rate_limit.exceeded",
                path=path,
                tenant_id=tenant_id,
                ip=_client_ip(request),
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
