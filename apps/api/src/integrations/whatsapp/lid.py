"""@lid contact phone resolver (read side).

Modern Brazilian WhatsApp accounts use the privacy ``@lid`` JID in webhook
payloads, masking the real phone number. Evolution 2.2.3 drops the
``sender_pn`` mapping field, so the webhook handler alone can't translate
the JID back to a phone.

The companion sidecar (:mod:`src.sidecars.lid_resolver`) tails Evolution's
stdout, parses ``(message_id, sender_pn)`` from Baileys ``recv`` events,
and caches the mapping under ``lid_pn:{message_id}`` in Redis with a 24 h
TTL. This module is the read side: given a ``provider_message_id``, look
up the resolved phone number.

Returns ``None`` when:
  * No mapping was cached yet (race: the sidecar hadn't seen the line)
  * The TTL expired
  * Redis is unreachable

Callers (the webhook handler) treat ``None`` as "fall back to whatever the
provider gave us" and log a warning so we can spot resolution gaps.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "lid_pn:"
# decode_responses=True below means values come back as str, not bytes.
_client_singleton: aioredis.Redis[str] | None = None


def _client() -> aioredis.Redis[str] | None:
    global _client_singleton
    if _client_singleton is None:
        try:
            _client_singleton = aioredis.from_url(
                str(get_settings().redis_url),
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
            )
        except Exception as exc:
            logger.warning("lid.redis_connect_failed", error=str(exc))
            return None
    return _client_singleton


async def resolve_lid_phone(message_id: str) -> str | None:
    """Return the cached phone digits for a given @lid message, or None."""
    if not message_id:
        return None
    client = _client()
    if client is None:
        return None
    try:
        return await client.get(_KEY_PREFIX + message_id)
    except Exception as exc:
        logger.warning("lid.redis_get_failed", message_id=message_id, error=str(exc))
        return None


def _reset_client_for_tests() -> None:
    """Test-only hook: drop the cached client so monkeypatched envs take effect."""
    global _client_singleton
    _client_singleton = None
