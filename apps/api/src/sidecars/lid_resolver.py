"""Sidecar that tails Evolution stdout for sender_pn / message_id pairs.

Evolution 2.2.3 drops Baileys' ``sender_pn`` field from its webhook payload
but still prints it to stdout via the pino logger when ``LOG_BAILEYS=debug``.
This daemon tails the Evolution container's stdout through the Docker
socket, extracts ``(message_id, sender_pn)`` from every Baileys ``recv``
event for a text message, and caches the mapping in Redis under
``lid_pn:{message_id}`` with a 24 h TTL.

The webhook handler then looks up the cache to translate the masked
``@lid`` JID back into a real WhatsApp phone before queueing the Celery
task. Without this hop, modern Brazilian WA accounts (privacy mode on by
default) can never receive a reply because Evolution's ``sendText`` returns
``400 {"exists":false}`` for ``@lid`` numbers.

Run as its own container::

    python -m src.sidecars.lid_resolver

Env vars:
    EVOLUTION_CONTAINER  Evolution container name (default ``encaixe-evolution``)
    REDIS_URL            Redis DSN (default ``redis://redis:6379/0``)
    LID_TTL_SECONDS      Per-key TTL (default ``86400``)

The Docker socket must be bind-mounted at ``/var/run/docker.sock``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Iterator

import docker
import redis
from docker.errors import DockerException, NotFound

from src.core.logging import get_logger

logger = get_logger(__name__)

_CONTAINER_DEFAULT = "encaixe-evolution"
_REDIS_DEFAULT = "redis://redis:6379/0"
_TTL_DEFAULT = 24 * 3600


def parse_recv_line(line: str | bytes) -> tuple[str, str] | None:
    """Extract ``(message_id, phone_digits)`` from one Evolution stdout line.

    Returns ``None`` if the line is not a Baileys ``recv`` event for a text
    message with a ``sender_pn`` field. Phone digits are stripped of the
    ``@s.whatsapp.net`` suffix.

    Pure function so it can be unit-tested without docker or redis. Tolerates
    non-JSON lines because ``LOG_BAILEYS=debug`` mixes pino JSON with plain
    ``LOG`` prefixes on the same stream.
    """
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    line = line.strip()
    if not line:
        return None
    # Fast reject: avoid the json.loads cost for the dominant case (non-recv
    # lines, receipts, notifications, plain LOG lines, etc).
    if '"recv"' not in line or '"sender_pn"' not in line:
        return None
    brace = line.find("{")
    if brace == -1:
        return None
    try:
        obj = json.loads(line[brace:])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    recv = obj.get("recv")
    if not isinstance(recv, dict):
        return None
    if recv.get("tag") != "message":
        return None
    attrs = recv.get("attrs")
    if not isinstance(attrs, dict):
        return None
    if attrs.get("type") != "text":
        return None
    msg_id = attrs.get("id")
    sender_pn = attrs.get("sender_pn")
    if not isinstance(msg_id, str) or not isinstance(sender_pn, str):
        return None
    phone = sender_pn.split("@", 1)[0]
    if not phone or not phone.isdigit():
        return None
    return msg_id, phone


def iter_log_lines(stream: Iterator[bytes]) -> Iterator[bytes]:
    """Buffer a raw docker-logs byte stream into newline-delimited lines.

    ``container.logs(stream=True)`` returns chunks that may contain zero or
    more newlines plus partial trailing lines. This generator yields one
    complete line per iteration; the final partial chunk is yielded only at
    stream end (which, with ``follow=True``, never happens in steady state).
    """
    buf = b""
    for chunk in stream:
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line
    if buf:
        yield buf


def _run_once() -> None:
    container_name = os.environ.get("EVOLUTION_CONTAINER", _CONTAINER_DEFAULT)
    redis_url = os.environ.get("REDIS_URL", _REDIS_DEFAULT)
    ttl = int(os.environ.get("LID_TTL_SECONDS", str(_TTL_DEFAULT)))

    rds = redis.Redis.from_url(redis_url, decode_responses=True)
    client = docker.from_env()

    try:
        container = client.containers.get(container_name)
    except NotFound:
        logger.error("lid_resolver.container_not_found", name=container_name)
        sys.exit(1)

    logger.info(
        "lid_resolver.started",
        container=container_name,
        container_id=container.id[:12],
        redis_url=redis_url,
        ttl_seconds=ttl,
    )

    raw_stream = container.logs(
        stream=True,
        follow=True,
        tail=0,
        stdout=True,
        stderr=True,
    )
    cached = 0
    for raw in iter_log_lines(raw_stream):
        pair = parse_recv_line(raw)
        if pair is None:
            continue
        msg_id, phone = pair
        try:
            rds.set(f"lid_pn:{msg_id}", phone, ex=ttl)
        except redis.RedisError as exc:
            logger.warning(
                "lid_resolver.redis_set_failed",
                msg_id=msg_id,
                error=str(exc),
            )
            continue
        cached += 1
        logger.info(
            "lid_resolver.cached",
            msg_id=msg_id,
            phone=phone,
            total=cached,
        )


def main() -> None:
    """Daemon entrypoint with crash-restart loop."""
    while True:
        try:
            _run_once()
        except (DockerException, ConnectionError) as exc:
            logger.warning(
                "lid_resolver.docker_error_restarting",
                error=str(exc),
            )
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("lid_resolver.shutdown_signal")
            return


if __name__ == "__main__":
    main()
