"""Pure parser for Baileys ``recv`` lines (@lid sender_pn intercept).

The function in this file is the canonical reference for parsing
Evolution's stdout into ``(message_id, sender_pn)`` pairs. The
production daemon — :mod:`apps.evolution.lid_pipe` — runs inside the
Evolution container image and intentionally vendors a byte-for-byte
copy of :func:`parse_recv_line` because that file can't import across
Docker build contexts. The tests in :mod:`tests.sidecars.test_lid_parser`
exercise the function here; when you change the parser, mirror the
change in ``apps/evolution/lid_pipe.py``.

History: an earlier version of this module also shipped a Docker-SDK
daemon that streamed logs from the Evolution container via
``/var/run/docker.sock``. That worked under docker-compose but cannot
run on Railway (no shared socket between services). The daemon was
removed in favour of the embedded ``lid_pipe.py`` design, which works
both locally and on Railway without any environment-specific code path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator


def parse_recv_line(line: str | bytes) -> tuple[str, str] | None:
    """Extract ``(message_id, phone_digits)`` from one Evolution stdout line.

    Returns ``None`` if the line is not a Baileys ``recv`` event for a
    text message with a ``sender_pn`` field. Phone digits are stripped
    of the ``@s.whatsapp.net`` suffix.

    Pure function — tolerates non-JSON lines because ``LOG_BAILEYS=debug``
    mixes pino JSON with plain ``LOG`` prefixes on the same stream.
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
    """Buffer a raw byte stream into newline-delimited lines.

    Kept here for historical reasons (the deleted Docker-SDK daemon used
    it to reassemble chunks from ``container.logs(stream=True)``). The
    production daemon in ``apps/evolution/lid_pipe.py`` doesn't need it
    — Python's text-mode subprocess pipe already yields whole lines via
    iteration — but tests still exercise the buffering behavior in case
    we ever bring back a chunked-stream reader.
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
