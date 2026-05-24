#!/usr/bin/env python3
"""@lid sender_pn intercept — runs Evolution as a child process.

Lives inside the Evolution container image. This is the production variant
of the @lid resolver: Railway gives each service its own container with no
shared `/var/run/docker.sock`, so the original sidecar-style daemon in
`apps/api/src/sidecars/lid_resolver.py` (which streams Evolution logs via
the Docker SDK) cannot work. Co-locating the parser inside the Evolution
container itself sidesteps the missing socket entirely.

What it does
------------
1. Spawns Evolution's original entrypoint (`. deploy_database.sh && npm
   run start:prod`) as a child process.
2. Forwards SIGTERM / SIGINT to the child so Railway's graceful shutdown
   still works.
3. Reads the child's combined stdout/stderr line by line.
4. Mirrors every line to its *own* stdout so the Railway log viewer still
   shows Evolution's logs unchanged.
5. When a line is a Baileys ``recv`` event for a text message carrying a
   ``sender_pn`` field, writes ``lid_pn:{message_id} -> {phone_digits}``
   to Redis with a 24 h TTL. The API webhook reads that key when it sees
   an ``@lid`` JID and patches ``contact_phone`` before queueing the
   Celery task.

The parser (``parse_recv_line``) is intentionally a copy of the one in
``apps/api/src/sidecars/lid_resolver.py``. The two files cannot share an
import because they live in separate Docker build contexts; the parser is
a stable ~30-line pure function, so duplication is cheaper than
introducing a shared build layer or a Python package. If you change the
log shape here, mirror the change there (and update the parser tests in
``apps/api/tests/sidecars/test_lid_parser.py``).

Env vars
--------
REDIS_URL        Where to write `lid_pn:*` keys. Default
                 ``redis://localhost:6379/0``. On Railway this gets
                 injected by terraform from the Redis plugin URL.
LID_TTL_SECONDS  Per-key TTL. Default ``86400`` (24 h).

The script becomes PID 1 inside the container. Evolution's exit code is
the script's exit code.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import types
from typing import Optional

try:
    import redis
except ImportError:  # pragma: no cover — image install missing
    sys.stderr.write(
        "[lid_pipe] redis-py is not installed; entering passthrough mode.\n"
    )
    redis = None  # type: ignore[assignment]


_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_LID_TTL = int(os.environ.get("LID_TTL_SECONDS", "86400"))


def parse_recv_line(line: str) -> Optional[tuple[str, str]]:
    """Extract ``(message_id, phone_digits)`` from one Evolution stdout line.

    Returns ``None`` for anything that isn't a Baileys ``recv`` event for
    a text message carrying a ``sender_pn`` field. The function is pure
    so it can be unit-tested with the same fixtures as the Docker-SDK
    sidecar (see ``apps/api/tests/sidecars/test_lid_parser.py``).
    """
    line = line.strip()
    if not line:
        return None
    # Fast reject: avoid the json.loads cost for the dominant case (Evolution
    # mixes pino JSON with plain `LOG ` prefixes on the same stream).
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
    if not isinstance(recv, dict) or recv.get("tag") != "message":
        return None
    attrs = recv.get("attrs")
    if not isinstance(attrs, dict) or attrs.get("type") != "text":
        return None
    msg_id = attrs.get("id")
    sender_pn = attrs.get("sender_pn")
    if not isinstance(msg_id, str) or not isinstance(sender_pn, str):
        return None
    phone = sender_pn.split("@", 1)[0]
    if not phone or not phone.isdigit():
        return None
    return msg_id, phone


def _connect_redis() -> "redis.Redis | None":
    if redis is None:
        return None
    try:
        client = redis.Redis.from_url(_REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[lid_pipe] redis connect failed: {exc}\n")
        return None


def _log(msg: str) -> None:
    sys.stderr.write(f"[lid_pipe] {msg}\n")
    sys.stderr.flush()


def main(child_cmd: list[str]) -> int:
    if not child_cmd:
        sys.stderr.write("[lid_pipe] usage: lid_pipe.py <command> [args...]\n")
        return 2

    rds = _connect_redis()
    if rds is not None:
        _log(f"started; mirroring child={child_cmd[0]} redis={_REDIS_URL} ttl={_LID_TTL}s")
    else:
        _log(f"started without redis (passthrough only); child={child_cmd[0]}")

    proc = subprocess.Popen(
        child_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )

    def _forward(sig: int, _frame: "types.FrameType | None") -> None:
        # Propagate Railway/Docker stop signals to the child. The pipe
        # closes on its own once the child exits and the for-loop ends.
        proc.send_signal(sig)

    signal.signal(signal.SIGTERM, _forward)
    signal.signal(signal.SIGINT, _forward)

    cached = 0
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            # Mirror to our own stdout so Railway's log viewer still sees
            # Evolution's output unchanged.
            sys.stdout.write(line)
            sys.stdout.flush()

            if rds is None:
                continue
            pair = parse_recv_line(line)
            if pair is None:
                continue
            msg_id, phone = pair
            try:
                rds.set(f"lid_pn:{msg_id}", phone, ex=_LID_TTL)
                cached += 1
                _log(f"cached msg_id={msg_id} phone={phone} total={cached}")
            except Exception as exc:  # noqa: BLE001
                _log(f"redis_set_failed msg_id={msg_id} err={exc}")
    except KeyboardInterrupt:
        proc.terminate()

    return proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
