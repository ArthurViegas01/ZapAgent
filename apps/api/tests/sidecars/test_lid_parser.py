"""Unit tests for the Evolution stdout parser used by the @lid sidecar.

The lines below are real samples captured from ``docker logs
encaixe-evolution`` on 2026-05-24 during the end-to-end pairing test.
Keep them verbatim — the parser exists exactly to survive these shapes.
"""

from __future__ import annotations

from src.sidecars.lid_resolver import iter_log_lines, parse_recv_line

# A Baileys 'recv' for a text message — the one shape we *do* want to cache.
TEXT_RECV = (
    '{"level":20,"time":1779645967794,"pid":268,"hostname":"e20f30faecfe",'
    '"recv":{"tag":"message","attrs":{"from":"265884312559697:56@lid","type":"text",'
    '"id":"3EB0C8ADEC0C8974F7E361","notify":"lorenzo","sender_pn":"555191079110@s.whatsapp.net",'
    '"t":"1779645967"}},"sent":{"id":"3EB0C8ADEC0C8974F7E361","to":"265884312559697:56@lid",'
    '"class":"message","type":"text"},"msg":"sent ack"}'
)

# A device-notification recv — no sender_pn, must be ignored.
NOTIFICATION_RECV = (
    '{"level":20,"time":1779646299367,"pid":268,"hostname":"e20f30faecfe",'
    '"recv":{"tag":"notification","attrs":{"from":"103581894078472@lid","type":"devices",'
    '"id":"580152507","t":"1779646296"}},"sent":{"id":"580152507","to":"103581894078472@lid",'
    '"class":"notification","type":"devices"},"msg":"sent ack"}'
)

# A receipt event — tag="receipt", no sender_pn.
RECEIPT_RECV = (
    '{"level":20,"time":1779645979507,"pid":268,"hostname":"e20f30faecfe",'
    '"recv":{"tag":"receipt","attrs":{"from":"55186118688892:82@lid","type":"read",'
    '"id":"3EB0C8ADEC0C8974F7E361","recipient":"265884312559697@lid","t":"1779645979"}},'
    '"sent":{},"msg":"sent ack"}'
)

# Plain Evolution LOG line that gets mixed onto the same stdout stream.
PLAIN_LOG = (
    "[Evolution API] [enc-d4445b-ac8965ff] 268 - Sun May 24 2026 15:06:07   "
    "LOG  [ChannelStartupService] [string] Update not read messages 265884312559697@lid"
)


def test_text_recv_line_yields_msgid_and_phone() -> None:
    out = parse_recv_line(TEXT_RECV)
    assert out == ("3EB0C8ADEC0C8974F7E361", "555191079110")


def test_text_recv_line_works_as_bytes() -> None:
    """Docker logs stream returns bytes; the parser must accept either."""
    out = parse_recv_line(TEXT_RECV.encode("utf-8"))
    assert out == ("3EB0C8ADEC0C8974F7E361", "555191079110")


def test_notification_recv_is_skipped() -> None:
    assert parse_recv_line(NOTIFICATION_RECV) is None


def test_receipt_event_is_skipped() -> None:
    assert parse_recv_line(RECEIPT_RECV) is None


def test_plain_log_line_is_skipped() -> None:
    assert parse_recv_line(PLAIN_LOG) is None


def test_empty_and_whitespace_lines_are_skipped() -> None:
    assert parse_recv_line("") is None
    assert parse_recv_line(b"") is None
    assert parse_recv_line("   \n") is None


def test_malformed_json_is_skipped() -> None:
    """A truncated chunk must not crash the daemon."""
    assert parse_recv_line('{"recv":{"sender_pn": "broken') is None


def test_non_text_message_is_skipped() -> None:
    """Image/audio messages have type != 'text' and shouldn't poison the
    cache (different message id, different recv shape).
    """
    line = (
        '{"recv":{"tag":"message","attrs":{"from":"x@lid","type":"image",'
        '"id":"IMG1","sender_pn":"555199999999@s.whatsapp.net"}}}'
    )
    assert parse_recv_line(line) is None


def test_sender_pn_without_digits_is_rejected() -> None:
    """Defensive: never cache a phone that doesn't look like digits."""
    line = (
        '{"recv":{"tag":"message","attrs":{"from":"x@lid","type":"text",'
        '"id":"X1","sender_pn":"notaphone@s.whatsapp.net"}}}'
    )
    assert parse_recv_line(line) is None


def test_empty_sender_pn_is_rejected() -> None:
    line = (
        '{"recv":{"tag":"message","attrs":{"from":"x@lid","type":"text",'
        '"id":"X1","sender_pn":"@s.whatsapp.net"}}}'
    )
    assert parse_recv_line(line) is None


def test_missing_sender_pn_is_rejected() -> None:
    """A pre-privacy WA message (sender_pn absent) shouldn't be cached —
    its from-jid is already a valid phone, no resolution needed.
    """
    line = (
        '{"recv":{"tag":"message","attrs":{"from":"555191079110@s.whatsapp.net",'
        '"type":"text","id":"X1"}}}'
    )
    # No 'sender_pn' substring -> fast-rejected before json.loads.
    assert parse_recv_line(line) is None


def test_iter_log_lines_handles_chunk_boundaries() -> None:
    """docker.logs() returns arbitrary chunks; lines may split mid-byte.

    Feed two chunks where one line spans the boundary and confirm the
    line buffer reassembles them correctly.
    """
    chunks = [b"first line\nsecond ", b"half\nthird line\n"]
    out = list(iter_log_lines(iter(chunks)))
    assert out == [b"first line", b"second half", b"third line"]


def test_iter_log_lines_skips_empty_chunks() -> None:
    chunks = [b"", b"alpha\n", b""]
    out = list(iter_log_lines(iter(chunks)))
    assert out == [b"alpha"]
