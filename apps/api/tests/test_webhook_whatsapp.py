"""Integration tests for the WhatsApp Evolution webhook handler.

All tests use FastAPI's TestClient (sync ASGI) so they run without a real
Evolution instance. Database calls are intercepted via asyncpg mock.
Celery task dispatch is patched to avoid Redis dependency.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVO_KEY = "test-evo-key"
INSTANCE = "zapagent-00000000"

INBOUND_MESSAGE_BODY = {
    "event": "messages.upsert",
    "instance": INSTANCE,
    "data": {
        "key": {
            "remoteJid": "5511999990001@s.whatsapp.net",
            "fromMe": False,
            "id": "ABCDEF123456",
        },
        "message": {"conversation": "Quero agendar um horário"},
        "pushName": "Test User",
    },
}

QRCODE_BODY = {
    "event": "qrcode.updated",
    "instance": INSTANCE,
    "data": {
        "qrcode": {
            "base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        }
    },
}

CONNECTION_OPEN_BODY = {
    "event": "connection.update",
    "instance": INSTANCE,
    "data": {"state": "open"},
}

CONNECTION_CLOSE_BODY = {
    "event": "connection.update",
    "instance": INSTANCE,
    "data": {"state": "close"},
}


def _make_mock_pool(tenant_id: str | None = "tenant-uuid-001") -> MagicMock:
    """Create a mock asyncpg Pool that returns predictable values."""
    pool = MagicMock()
    conn = AsyncMock()
    # Mock acquire() as an async context manager.
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    # _record_webhook_event INSERT → unique (return True = new record)
    conn.execute = AsyncMock(return_value=None)

    # _resolve_tenant → returns tenant_id or None
    tenant_row = {"tenant_id": tenant_id} if tenant_id else None
    # _upsert_conversation → returns conversation uuid
    conv_row = {"id": "conv-uuid-001"}
    # _check_opted_out → not opted out
    opted_row = {"opted_out": False}

    conn.fetchrow = AsyncMock(side_effect=[
        None,  # UniqueViolationError won't fire (execute mock) — fetchrow for tenant
        tenant_row,    # _resolve_tenant
        conv_row,      # _upsert_conversation
        opted_row,     # opted_out check
    ])

    # UniqueViolationError path: execute succeeds (not duplicate)
    return pool


@pytest.fixture
def app_with_pool():
    """FastAPI app with a mock DB pool attached to state."""
    app = create_app()
    pool = _make_mock_pool()
    app.state.db_pool = pool
    return app, pool


@pytest.fixture
def client(app_with_pool):
    app, _ = app_with_pool
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_webhook_rejects_wrong_api_key(client: TestClient) -> None:
    resp = client.post(
        "/webhooks/whatsapp",
        json=INBOUND_MESSAGE_BODY,
        headers={"apikey": "wrong-key"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_correct_api_key(client: TestClient) -> None:
    with patch("src.worker.tasks.process_whatsapp_message.delay"):
        resp = client.post(
            "/webhooks/whatsapp",
            json=INBOUND_MESSAGE_BODY,
            headers={"apikey": EVO_KEY},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Event routing — non-message events
# ---------------------------------------------------------------------------

def test_webhook_skips_unknown_event(client: TestClient) -> None:
    body = {"event": "contacts.upsert", "instance": INSTANCE, "data": {}}
    resp = client.post("/webhooks/whatsapp", json=body, headers={"apikey": EVO_KEY})
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "contacts.upsert"


def test_webhook_skips_outbound_message(client: TestClient) -> None:
    body = {**INBOUND_MESSAGE_BODY}
    body["data"] = {**INBOUND_MESSAGE_BODY["data"], "key": {**INBOUND_MESSAGE_BODY["data"]["key"], "fromMe": True}}
    resp = client.post("/webhooks/whatsapp", json=body, headers={"apikey": EVO_KEY})
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "outbound"


def test_webhook_skips_non_text_message(client: TestClient) -> None:
    body = {
        "event": "messages.upsert",
        "instance": INSTANCE,
        "data": {
            "key": {"remoteJid": "5511@s.whatsapp.net", "fromMe": False, "id": "XYZ"},
            "message": {"imageMessage": {}},  # no conversation/text
        },
    }
    resp = client.post("/webhooks/whatsapp", json=body, headers={"apikey": EVO_KEY})
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "no_text"


# ---------------------------------------------------------------------------
# QR code webhook
# ---------------------------------------------------------------------------

def test_webhook_stores_qr_on_qrcode_updated(app_with_pool) -> None:
    app, pool = app_with_pool
    # Reset pool conn for this specific test.
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)

    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=QRCODE_BODY, headers={"apikey": EVO_KEY})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # DB UPDATE should have been called with the qr blob.
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert '"qrcode"' in call_args[1]  # JSON payload contains qrcode key


def test_webhook_handles_qrcode_without_pool() -> None:
    app = create_app()
    app.state.db_pool = None
    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=QRCODE_BODY, headers={"apikey": EVO_KEY})
    # Should still return 200 (no pool is a graceful degradation).
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Connection update webhook
# ---------------------------------------------------------------------------

def test_webhook_marks_connected_on_open_state(app_with_pool) -> None:
    app, pool = app_with_pool
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)

    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=CONNECTION_OPEN_BODY, headers={"apikey": EVO_KEY})

    assert resp.status_code == 200
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "connected" in sql


def test_webhook_marks_pending_on_close_state(app_with_pool) -> None:
    app, pool = app_with_pool
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)

    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=CONNECTION_CLOSE_BODY, headers={"apikey": EVO_KEY})

    assert resp.status_code == 200
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "pending" in sql


# ---------------------------------------------------------------------------
# Full inbound message pipeline
# ---------------------------------------------------------------------------

def test_webhook_returns_tenant_none_when_not_found() -> None:
    app = create_app()
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    # insert succeeds (not duplicate)
    conn.execute = AsyncMock(return_value=None)
    # _resolve_tenant returns None
    conn.fetchrow = AsyncMock(return_value=None)
    app.state.db_pool = pool

    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=INBOUND_MESSAGE_BODY, headers={"apikey": EVO_KEY})

    assert resp.status_code == 200
    assert resp.json()["tenant"] is None


def test_webhook_enqueues_celery_task_for_valid_message(app_with_pool) -> None:
    app, pool = app_with_pool
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value=None)
    # Sequence: webhook_events INSERT ok, resolve_tenant, upsert_conv, update_tenant_id, opted_out
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": "tenant-uuid-001"},   # _resolve_tenant
        {"id": "conv-uuid-001"},             # _upsert_conversation
        {"opted_out": False},                # opted_out check
    ])

    with patch("src.worker.tasks.process_whatsapp_message.delay") as mock_delay:
        with TestClient(app) as c:
            resp = c.post("/webhooks/whatsapp", json=INBOUND_MESSAGE_BODY, headers={"apikey": EVO_KEY})

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("queued") is True
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs["tenant_id"] == "tenant-uuid-001"
    assert call_kwargs["contact_phone"] == "5511999990001"
    assert "Quero agendar" in call_kwargs["user_message"]
