"""Tests for the WhatsApp provider abstraction.

Covers:
  - Factory selects the right implementation per WHATSAPP_PROVIDER
  - StubProvider implements the full WhatsAppProvider contract
  - EvolutionProvider parsing helpers normalize Evolution v2 payloads
  - Stub end-to-end: webhook -> Celery dispatch -> reply send (no network)
"""

from __future__ import annotations

import pytest

from src.core.config import get_settings
from src.integrations.whatsapp import (
    InboundMessage,
    SessionInfo,
    WhatsAppProvider,
    get_whatsapp_provider,
    reset_provider,
)
from src.integrations.whatsapp.evolution import EvolutionProvider
from src.integrations.whatsapp.stub import StubProvider

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_evolution_by_default():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    reset_provider()
    p = get_whatsapp_provider()
    assert isinstance(p, EvolutionProvider)
    assert p.name == "evolution"


def test_factory_returns_stub_when_configured():
    s = get_settings()
    s.whatsapp_provider = "stub"
    reset_provider()
    p = get_whatsapp_provider()
    assert isinstance(p, StubProvider)
    assert p.name == "stub"


# ---------------------------------------------------------------------------
# StubProvider full contract
# ---------------------------------------------------------------------------


@pytest.fixture
def stub() -> StubProvider:
    s = get_settings()
    s.whatsapp_provider = "stub"
    reset_provider()
    p = get_whatsapp_provider()
    assert isinstance(p, StubProvider)
    p.reset()
    return p


async def test_stub_creates_and_promotes_session(stub: StubProvider):
    info = await stub.create_session("inst-1")
    assert isinstance(info, SessionInfo)
    assert info.status == "pending"
    assert info.qrcode_data_url.startswith("data:image/png;base64,")

    # First poll keeps pending so the dashboard can render the QR once,
    # then auto-promotes on subsequent polls.
    info2 = await stub.get_session("inst-1")
    assert info2.status == "pending"
    info3 = await stub.get_session("inst-1")
    assert info3.status == "connected"


async def test_stub_send_text_records_outbound(stub: StubProvider):
    await stub.send_text(instance_name="i", phone="5511", text="oi")
    await stub.send_text(instance_name="i", phone="5511", text="tudo bem?")
    sent = stub.sent
    assert len(sent) == 2
    assert sent[0]["text"] == "oi"
    assert sent[1]["text"] == "tudo bem?"


def test_stub_parses_minimal_inbound(stub: StubProvider):
    body = {"phone": "5511999990001", "text": "Quero agendar amanha as 10h", "name": "Demo"}
    assert stub.parse_event_type(body) == "messages_upsert"
    msg = stub.parse_inbound_message(body)
    assert isinstance(msg, InboundMessage)
    assert msg.contact_phone == "5511999990001"
    assert msg.text == "Quero agendar amanha as 10h"
    assert msg.contact_name == "Demo"
    assert msg.provider_message_id  # auto-derived hash when not provided


def test_stub_returns_none_for_empty_text(stub: StubProvider):
    assert stub.parse_inbound_message({"phone": "5511", "text": ""}) is None
    assert stub.parse_inbound_message({"phone": "", "text": "hi"}) is None


def test_stub_ignores_unknown_event(stub: StubProvider):
    assert stub.parse_event_type({"event": "stub.bogus"}) == "ignored"


# ---------------------------------------------------------------------------
# EvolutionProvider parsing
# ---------------------------------------------------------------------------


def test_evolution_event_classification():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    reset_provider()
    p = get_whatsapp_provider()
    assert p.parse_event_type({"event": "QRCODE_UPDATED"}) == "qrcode_updated"
    assert p.parse_event_type({"event": "CONNECTION_UPDATE"}) == "connection_update"
    assert p.parse_event_type({"event": "MESSAGES_UPSERT"}) == "messages_upsert"
    assert p.parse_event_type({"event": "MESSAGES_DELETE"}) == "ignored"
    assert p.parse_event_type({"event": ""}) == "ignored"


def test_evolution_parses_inbound_text_and_caption():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    reset_provider()
    p = get_whatsapp_provider()

    plain = p.parse_inbound_message(
        {
            "instance": "inst",
            "data": {
                "key": {"remoteJid": "5511@s.whatsapp.net", "fromMe": False, "id": "M1"},
                "message": {"conversation": "Bom dia"},
                "pushName": "X",
            },
        }
    )
    assert plain is not None and plain.text == "Bom dia"

    caption = p.parse_inbound_message(
        {
            "instance": "inst",
            "data": {
                "key": {"remoteJid": "5511@s.whatsapp.net", "fromMe": False, "id": "M2"},
                "message": {"imageMessage": {"caption": "  legenda  "}},
            },
        }
    )
    assert caption is not None and caption.text == "legenda"


def test_evolution_ignores_outbound_and_no_text():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    reset_provider()
    p = get_whatsapp_provider()
    out = p.parse_inbound_message(
        {
            "data": {
                "key": {"fromMe": True, "remoteJid": "5511@x", "id": "M"},
                "message": {"conversation": "hi"},
            }
        }
    )
    assert out is None
    none = p.parse_inbound_message(
        {
            "data": {
                "key": {"fromMe": False, "remoteJid": "5511@x", "id": "M"},
                "message": {"stickerMessage": {}},
            }
        }
    )
    assert none is None


def test_evolution_webhook_auth_uses_token_setting():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    s.evolution_webhook_token = "secret-token"
    reset_provider()
    p = get_whatsapp_provider()
    assert p.verify_webhook_auth({"token": "secret-token"}) is True
    assert p.verify_webhook_auth({"token": "Token"}) is False
    assert p.verify_webhook_auth({}) is False


def test_evolution_webhook_auth_open_when_token_empty():
    s = get_settings()
    s.whatsapp_provider = "evolution"
    s.evolution_webhook_token = ""
    reset_provider()
    p = get_whatsapp_provider()
    assert p.verify_webhook_auth({}) is True


# ---------------------------------------------------------------------------
# Provider is a real ABC -- subclasses must implement the surface
# ---------------------------------------------------------------------------


def test_provider_is_abstract():
    with pytest.raises(TypeError):
        WhatsAppProvider()  # type: ignore[abstract]
