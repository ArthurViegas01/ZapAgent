"""WhatsApp provider port (hexagonal architecture).

The agent pipeline never talks to a specific WhatsApp gateway directly.
It depends on this abstract interface so we can:

* run end-to-end tests without a real WhatsApp account (StubProvider)
* swap Evolution API <-> WPP Connect <-> Meta Cloud API <-> Twilio
  with a single env var change
* keep webhook normalization in one place (provider implementations
  translate vendor payload shape into a uniform InboundEvent)

Adding a new provider:

  1. Subclass ``WhatsAppProvider`` and implement every abstract method.
  2. Register it in ``factory.py``.
  3. Add the ``Literal`` value to ``settings.whatsapp_provider``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

EventType = Literal[
    "qrcode_updated",
    "connection_update",
    "messages_upsert",
    "ignored",
]


@dataclass(frozen=True)
class SessionInfo:
    """The state of a WhatsApp pairing/session, normalized across providers."""

    instance_name: str
    status: Literal["pending", "connected", "revoked", "error"]
    qrcode_data_url: str = ""  # base64 data URL ready for <img src="...">


@dataclass(frozen=True)
class InboundMessage:
    """A normalized inbound text message ready for the agent pipeline.

    Providers translate their vendor payload into this shape; the rest of
    the system is provider-agnostic from here on.
    """

    instance_name: str
    provider_message_id: str  # used for idempotency
    contact_phone: str  # E.164-ish digits, no @s.whatsapp.net suffix
    contact_name: str | None
    text: str
    is_from_me: bool


@dataclass(frozen=True)
class ConnectionUpdate:
    """A normalized session/connection state change."""

    instance_name: str
    state: Literal["open", "close", "refused", "connecting", "unknown"]


class WhatsAppProvider(ABC):
    """Provider port. Implementations live alongside this file."""

    name: str  # short identifier surfaced in logs / health checks

    # -- session lifecycle --------------------------------------------------

    @abstractmethod
    async def create_session(self, instance_name: str) -> SessionInfo:
        """Provision a session and start the pairing flow.

        Returns immediately; the QR code may or may not be available yet.
        Callers should poll ``get_session`` until ``status == "connected"``
        or surface ``qrcode_data_url`` to the user.
        """

    @abstractmethod
    async def get_session(self, instance_name: str) -> SessionInfo:
        """Return current session state and (if pending) latest QR."""

    @abstractmethod
    async def delete_session(self, instance_name: str) -> None:
        """Tear down the session at the provider."""

    # -- outbound -----------------------------------------------------------

    @abstractmethod
    async def send_text(self, *, instance_name: str, phone: str, text: str) -> None:
        """Send a text message. Raises on transport error."""

    # -- inbound ------------------------------------------------------------

    @abstractmethod
    def parse_event_type(self, body: dict[str, Any]) -> EventType:
        """Classify an inbound webhook payload."""

    @abstractmethod
    def parse_qrcode(self, body: dict[str, Any]) -> str:
        """Return base64 data URL or '' if the payload has no QR."""

    @abstractmethod
    def parse_connection_update(self, body: dict[str, Any]) -> ConnectionUpdate:
        """Return normalized connection update."""

    @abstractmethod
    def parse_inbound_message(self, body: dict[str, Any]) -> InboundMessage | None:
        """Return normalized inbound message, or None to skip."""

    # -- webhook auth -------------------------------------------------------

    @abstractmethod
    def verify_webhook_auth(self, headers: dict[str, str]) -> bool:
        """Return True if the request is authentic."""
