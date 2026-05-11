"""In-memory WhatsApp provider for E2E tests, demos, and local-only dev.

The Stub provider lets you exercise the full pipeline without an Evolution
API key, a WhatsApp account, or any external network. It is safe to leave
on in CI: every send is recorded in a process-local list and discarded
when the process exits.

Inbound payload shape (intentionally tiny -- you POST it straight to
``/webhooks/whatsapp`` with header ``token: <evolution_webhook_token>``)::

    {
        "event": "stub.inbound",          # for logging only
        "instance": "demo-instance",
        "phone": "5511999999999",
        "text":  "Quero agendar amanha as 10h",
        "name":  "Cliente Demo",          # optional
        "id":    "msg_001"                # optional, defaults to a hash
    }

The session lifecycle is also faked: ``create_session`` returns a fake QR
data URL straight away and ``get_session`` flips to ``connected`` after the
first call so the dashboard's QR pairing flow renders end-to-end.
"""

from __future__ import annotations

import hashlib
from threading import Lock
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger

from .base import (
    ConnectionUpdate,
    EventType,
    InboundMessage,
    SessionInfo,
    WhatsAppProvider,
)

logger = get_logger(__name__)

# 1x1 transparent PNG as a placeholder QR payload.
_FAKE_QR_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class StubProvider(WhatsAppProvider):
    """Records outbound traffic in process memory and fakes session lifecycle."""

    name = "stub"

    def __init__(self) -> None:
        self._lock = Lock()
        self._sent: list[dict[str, str]] = []
        self._sessions: dict[str, str] = {}  # instance_name -> status

    # -- introspection (used by tests / demo runners) ---------------------

    @property
    def sent(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._sent)

    def reset(self) -> None:
        with self._lock:
            self._sent.clear()
            self._sessions.clear()

    # -- session lifecycle ------------------------------------------------

    async def create_session(self, instance_name: str) -> SessionInfo:
        with self._lock:
            self._sessions[instance_name] = "pending"
        logger.info("stub.session_created", instance=instance_name)
        return SessionInfo(
            instance_name=instance_name,
            status="pending",
            qrcode_data_url=_FAKE_QR_DATA_URL,
        )

    async def get_session(self, instance_name: str) -> SessionInfo:
        with self._lock:
            current = self._sessions.get(instance_name)
            if current is None:
                return SessionInfo(instance_name=instance_name, status="revoked")
            # Auto-promote to connected on second poll so the dashboard's
            # connection state machine progresses end-to-end in demos.
            if current == "pending":
                self._sessions[instance_name] = "connected"
                return SessionInfo(
                    instance_name=instance_name,
                    status="pending",
                    qrcode_data_url=_FAKE_QR_DATA_URL,
                )
            return SessionInfo(instance_name=instance_name, status="connected")

    async def delete_session(self, instance_name: str) -> None:
        with self._lock:
            self._sessions.pop(instance_name, None)
        logger.info("stub.session_deleted", instance=instance_name)

    # -- outbound ---------------------------------------------------------

    async def send_text(self, *, instance_name: str, phone: str, text: str) -> None:
        record = {"instance": instance_name, "phone": phone, "text": text}
        with self._lock:
            self._sent.append(record)
        logger.info("stub.send_text", **record, total_sent=len(self._sent))

    # -- inbound ----------------------------------------------------------

    def parse_event_type(self, body: dict[str, Any]) -> EventType:
        if not isinstance(body, dict):
            return "ignored"
        if body.get("event") == "stub.connection":
            return "connection_update"
        if body.get("event") == "stub.qrcode":
            return "qrcode_updated"
        # Any payload with phone+text is treated as an inbound message.
        if body.get("phone") and body.get("text"):
            return "messages_upsert"
        return "ignored"

    def parse_qrcode(self, body: dict[str, Any]) -> str:
        return _FAKE_QR_DATA_URL

    def parse_connection_update(self, body: dict[str, Any]) -> ConnectionUpdate:
        state_raw = str(body.get("state", "open")).lower()
        if state_raw not in ("open", "close", "refused", "connecting"):
            state_raw = "unknown"
        return ConnectionUpdate(
            instance_name=str(body.get("instance", "")),
            state=state_raw,  # type: ignore[arg-type]
        )

    def parse_inbound_message(self, body: dict[str, Any]) -> InboundMessage | None:
        phone = str(body.get("phone", "")).strip()
        text = str(body.get("text", "")).strip()
        if not phone or not text:
            return None
        msg_id = str(body.get("id") or "").strip()
        if not msg_id:
            msg_id = "stub_" + hashlib.sha1(f"{phone}:{text}".encode()).hexdigest()[:12]
        return InboundMessage(
            instance_name=str(body.get("instance", "")),
            provider_message_id=msg_id,
            contact_phone=phone,
            contact_name=body.get("name"),
            text=text,
            is_from_me=False,
        )

    # -- webhook auth -----------------------------------------------------

    def verify_webhook_auth(self, headers: dict[str, str]) -> bool:
        token = get_settings().evolution_webhook_token
        if not token:
            return True
        candidate = headers.get("token") or headers.get("Token") or headers.get("TOKEN") or ""
        return candidate == token
