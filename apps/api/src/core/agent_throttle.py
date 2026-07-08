"""Per-contact throttle for the agent path (ZAP-007).

Caps how many LLM-backed turns a single WhatsApp contact can trigger per day
for a given tenant, so one malicious contact cannot burn a paying tenant's LLM
budget. Best-effort: a Redis outage fails open and never blocks legit traffic.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)

_MAX_TURNS_PER_CONTACT_PER_DAY = 50
_WINDOW_SECONDS = 24 * 3600

_pool: aioredis.Redis | None = None


async def _redis() -> aioredis.Redis | None:
    global _pool
    if _pool is None:
        try:
            _pool = aioredis.from_url(
                str(get_settings().redis_url),
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
            )
        except Exception as exc:
            logger.warning("agent_throttle.redis_connect_failed", error=str(exc))
            return None
    return _pool


async def within_agent_quota(tenant_id: str, contact_phone: str) -> bool:
    """Return True if this contact may trigger another agent turn today.

    Fails open on any Redis problem: throttling must never take the pipeline
    down, it only caps abuse when Redis is healthy.
    """
    redis = await _redis()
    if redis is None:
        return True

    day = int(time.time()) // _WINDOW_SECONDS
    key = f"agent:turns:{tenant_id}:{contact_phone}:{day}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _WINDOW_SECONDS)
        count = (await pipe.execute())[0]
        return int(count) <= _MAX_TURNS_PER_CONTACT_PER_DAY
    except Exception as exc:
        logger.warning("agent_throttle.redis_error", error=str(exc))
        return True
