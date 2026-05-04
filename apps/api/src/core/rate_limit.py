"""Redis-based sliding-window rate limiter for FastAPI.

Strategy:
  - Authenticated routes:  120 requests / 60 s  per tenant_id
  - Unauthenticated routes: 30 requests / 60 s  per client IP
  - Exempt paths: /health, /webhooks/ (Evolution sends bursts of events)

Implementation uses Redis INCR + EXPIRE (atomic enough for our SLA).
"""

from __future__ import annotations

import time
from typing import Callable

import redis.asyncio as aioredis
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
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


def _extract_tenant_from_bearer(authorization: str) -> str | None:
    """Quick unverified claim extraction — rate key only, not auth."""
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    try:
        from jose import jwt  # noqa: PLC0415
        claims = jwt.get_unverified_claims(token)
        return (
            claims.get("app_metadata", {}).get("tenant_id")
            or claims.get("sub")
            or None
        )
    except Exception:  # noqa: BLE001
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

    async def _get_redis(self) -> aioredis.Redis | None:
        if self._pool is None:
            try:
                self._pool = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=1,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("rate_limit.redis_connect_failed", error=str(exc))
        return self._pool

    async def _check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Increment counter. Returns (allowed, requests_remaining)."""
        redis = await self._get_redis()
        if redis is None:
            return True, limit  # fail open if Redis is down

        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)
            results = await pipe.execute()
            count: int = results[0]
            remaining = max(0, limit - count)
            return count <= limit, remaining
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit.redis_error", error=str(exc))
            return True, limit  # fail open

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip exempt paths.
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

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
