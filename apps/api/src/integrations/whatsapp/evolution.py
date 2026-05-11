"""Evolution API v2 implementation of WhatsAppProvider.

Evolution sends events with these names when the instance is created with
``byEvents: false`` and ``base64: true``:

  qrcode.updated      -> data.qrcode.base64  (dot notation, normalized to underscore)
  connection.update   -> data.state in {open, close, refused, connecting}
  messages.upsert     -> data.{key, message, pushName}

parse_event_type normalizes dots→underscores and uppercases, so both
``byEvents=True`` (QRCODE_UPDATED) and ``byEvents=False`` (qrcode.updated)
resolve to the same internal EventType.

Webhook auth: when we create the instance we pass ``headers: {token: ...}``,
so Evolution sends that header on every event. We compare against
``settings.evolution_webhook_token``. The global ``apikey`` header is
intentionally not used for webhook auth (least privilege: the global key
gives admin access to every instance).
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import get_settings
from src.core.evolution_qr import evolution_qr_to_data_url
from src.core.logging import get_logger

from .base import (
    ConnectionUpdate,
    EventType,
    InboundMessage,
    SessionInfo,
    WhatsAppProvider,
)

logger = get_logger(__name__)


class EvolutionProvider(WhatsAppProvider):
    """Self-hosted Evolution API v2 (Baileys, no Chrome)."""

    name = "evolution"

    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.evolution_api_url.rstrip("/")
        self._api_key = s.evolution_api_key
        self._webhook_token = s.evolution_webhook_token
        self._webhook_url = s.evolution_webhook_base_url

    # -- helpers -----------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    def _admin_headers(self) -> dict[str, str]:
        return {"apikey": self._api_key, "Content-Type": "application/json"}

    # -- session lifecycle -------------------------------------------------

    async def create_session(self, instance_name: str) -> SessionInfo:
        body = {
            "instanceName": instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
            "webhook": {
                "url": self._webhook_url,
                "byEvents": False,
                "base64": True,
                "headers": {"token": self._webhook_token},
                "events": [
                    "QRCODE_UPDATED",
                    "CONNECTION_UPDATE",
                    "MESSAGES_UPSERT",
                ],
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url("instance/create"),
                json=body,
                headers=self._admin_headers(),
            )
            resp.raise_for_status()
        logger.info("evolution.instance_created", instance=instance_name)

        # Return immediately — do NOT call get_session or /instance/connect here.
        # Calling /instance/connect restarts the Baileys WebSocket handshake, which
        # interrupts QR generation. The QR arrives asynchronously via the
        # qrcode.updated webhook (stored in DB) and the frontend picks it up by
        # polling /whatsapp/status.
        return SessionInfo(instance_name=instance_name, status="pending", qrcode_data_url="")

    async def get_session(self, instance_name: str) -> SessionInfo:
        # Do NOT call /instance/connect here — that endpoint restarts the Baileys
        # WebSocket handshake each time it is called, which interrupts QR generation.
        # QR codes are delivered exclusively via the qrcode.updated webhook and stored
        # in the integrations.config column by the webhook handler. This method only
        # reads the current connection state for status display.
        state = "pending"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                state_resp = await client.get(
                    self._url(f"instance/connectionState/{instance_name}"),
                    headers=self._admin_headers(),
                )
            if state_resp.is_success:
                payload = state_resp.json() or {}
                inst = payload.get("instance") if isinstance(payload, dict) else None
                evo_state = (inst or {}).get("state", "") if isinstance(inst, dict) else ""
                if evo_state == "open":
                    state = "connected"
                elif evo_state in ("close", "refused"):
                    state = "revoked"
        except Exception as exc:  # noqa: BLE001
            logger.debug("evolution.state_check_failed", instance=instance_name, error=str(exc))

        return SessionInfo(instance_name=instance_name, status=state, qrcode_data_url="")  # type: ignore[arg-type]

    async def delete_session(self, instance_name: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.delete(
                    self._url(f"instance/delete/{instance_name}"),
                    headers=self._admin_headers(),
                )
            logger.info("evolution.instance_deleted", instance=instance_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("evolution.delete_failed", instance=instance_name, error=str(exc))

    # -- outbound ----------------------------------------------------------

    async def send_text(self, *, instance_name: str, phone: str, text: str) -> None:
        url = self._url(f"message/sendText/{instance_name}")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json={"number": phone, "text": text},
                headers=self._admin_headers(),
            )
            resp.raise_for_status()

    # -- inbound -----------------------------------------------------------

    def parse_event_type(self, body: dict[str, Any]) -> EventType:
        # Evolution sends events with dots when byEvents=False (e.g. "qrcode.updated",
        # "connection.update", "messages.upsert"). Normalize to underscores so we can
        # do a single comparison regardless of the byEvents setting.
        event = str(body.get("event", "")).upper().replace(".", "_")
        if event == "QRCODE_UPDATED":
            return "qrcode_updated"
        if event == "CONNECTION_UPDATE":
            return "connection_update"
        if event == "MESSAGES_UPSERT":
            return "messages_upsert"
        return "ignored"

    def parse_qrcode(self, body: dict[str, Any]) -> str:
        data = body.get("data", {}) if isinstance(body, dict) else {}
        return evolution_qr_to_data_url(data if isinstance(data, dict) else {})

    def parse_connection_update(self, body: dict[str, Any]) -> ConnectionUpdate:
        data = body.get("data", {}) or {}
        state_raw = str(data.get("state", "")).lower() if isinstance(data, dict) else ""
        if state_raw not in ("open", "close", "refused", "connecting"):
            state_raw = "unknown"
        return ConnectionUpdate(
            instance_name=str(body.get("instance", "")),
            state=state_raw,  # type: ignore[arg-type]
        )

    def parse_inbound_message(self, body: dict[str, Any]) -> InboundMessage | None:
        data = body.get("data", {}) or {}
        if not isinstance(data, dict):
            return None
        key = data.get("key", {}) or {}
        if not isinstance(key, dict):
            return None
        if key.get("fromMe", True):
            return None
        msg = data.get("message", {}) or {}
        if not isinstance(msg, dict):
            return None
        text = (
            msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or (msg.get("imageMessage") or {}).get("caption")
            or ""
        )
        text = (text or "").strip()
        if not text:
            return None
        jid = str(key.get("remoteJid", ""))
        phone = jid.split("@")[0]
        if not phone:
            return None
        return InboundMessage(
            instance_name=str(body.get("instance", "")),
            provider_message_id=str(key.get("id", "")),
            contact_phone=phone,
            contact_name=data.get("pushName") or None,
            text=text,
            is_from_me=False,
        )

    # -- webhook auth ------------------------------------------------------

    def verify_webhook_auth(self, headers: dict[str, str]) -> bool:
        if not self._webhook_token:
            return True  # auth disabled (dev/test mode)
        # Header names are case-insensitive at the HTTP layer; FastAPI
        # normalizes via Headers but pass-through dicts may not.
        token = headers.get("token") or headers.get("Token") or headers.get("TOKEN") or ""
        return token == self._webhook_token
