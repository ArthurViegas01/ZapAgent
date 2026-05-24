"""Testes de integração para o webhook handler Evolution API.

Todos os testes usam FastAPI TestClient (ASGI sync) sem precisar de
Evolution API real. As chamadas ao DB são interceptadas via mock asyncpg.
O dispatch Celery é patchado para não depender de Redis.

Formato de payload: Evolution API v2
  event: "QRCODE_UPDATED" | "CONNECTION_UPDATE" | "MESSAGES_UPSERT"
  instance: nome da instância
  data: payload específico do evento

Auth: header `token` com EVOLUTION_WEBHOOK_TOKEN.

Estratégia de injeção do pool:
  Patchamos src.db.pool.create_pool para que o lifespan do FastAPI
  configure app.state.db_pool com nosso mock pool.
  O patch e aplicado ANTES de abrir o TestClient (antes do lifespan rodar).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


# ---------------------------------------------------------------------------
# Constantes de teste
# ---------------------------------------------------------------------------

WEBHOOK_TOKEN = "test-webhook-token"
INSTANCE = "za-000000-abcd1234"

INBOUND_MESSAGE_BODY: dict[str, Any] = {
    "event": "MESSAGES_UPSERT",
    "instance": INSTANCE,
    "data": {
        "key": {
            "remoteJid": "5511999990001@s.whatsapp.net",
            "fromMe": False,
            "id": "ABCDEF123456",
        },
        "message": {
            "conversation": "Quero agendar um horario",
        },
        "pushName": "Test User",
    },
}

QRCODE_BODY: dict[str, Any] = {
    "event": "QRCODE_UPDATED",
    "instance": INSTANCE,
    "data": {
        "qrcode": {
            "base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        }
    },
}

CONNECTION_CONNECTED_BODY: dict[str, Any] = {
    "event": "CONNECTION_UPDATE",
    "instance": INSTANCE,
    "data": {
        "state": "open",
    },
}

CONNECTION_DISCONNECTED_BODY: dict[str, Any] = {
    "event": "CONNECTION_UPDATE",
    "instance": INSTANCE,
    "data": {
        "state": "close",
    },
}


# ---------------------------------------------------------------------------
# Helpers de mock
# ---------------------------------------------------------------------------

def _make_mock_pool(tenant_id: str | None = "tenant-uuid-001") -> MagicMock:
    """Cria um mock asyncpg Pool com valores previsiveis."""
    pool = MagicMock()
    pool.close = AsyncMock(return_value=None)

    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value=None)

    tenant_row = {"tenant_id": tenant_id} if tenant_id else None
    conn.fetchrow = AsyncMock(side_effect=[
        tenant_row,
        {"id": "conv-uuid-001"},
        {"opted_out": False},
        {"subscription_status": "active", "trial_ends_at": None},
    ])

    return pool


def _make_fresh_conn(pool: MagicMock) -> AsyncMock:
    """Substitui a conn do pool por um AsyncMock zerado e a retorna."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn


def _setup_webhook_token() -> None:
    from src.core.config import get_settings
    get_settings().evolution_webhook_token = WEBHOOK_TOKEN


def _token_headers() -> dict[str, str]:
    return {"token": WEBHOOK_TOKEN}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Client simples para testes que nao inspecionam operacoes no DB.

    O lifespan tenta criar o pool real, falha (sem DB), e db_pool fica
    None. Isso e suficiente para testes de roteamento e autenticacao.
    """
    _setup_webhook_token()
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_client():
    """App + Client com mock DB pool injetado via patch."""
    pool = _make_mock_pool()
    _setup_webhook_token()
    with patch("src.db.pool.create_pool", new=AsyncMock(return_value=pool)):
        app = create_app()
        with TestClient(app) as c:
            yield app, pool, c


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------

def test_webhook_rejects_wrong_token(client: TestClient) -> None:
    resp = client.post(
        "/webhooks/whatsapp",
        json=INBOUND_MESSAGE_BODY,
        headers={"token": "token-errado"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_correct_token(app_client) -> None:
    _, pool, c = app_client
    with patch("src.worker.tasks.process_whatsapp_message.delay"):
        resp = c.post(
            "/webhooks/whatsapp",
            json=INBOUND_MESSAGE_BODY,
            headers=_token_headers(),
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Roteamento de eventos
# ---------------------------------------------------------------------------

def test_webhook_skips_unknown_event(client: TestClient) -> None:
    body = {"event": "MESSAGES_DELETE", "instance": INSTANCE, "data": {}}
    resp = client.post("/webhooks/whatsapp", json=body, headers=_token_headers())
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "MESSAGES_DELETE"


def test_webhook_skips_outbound_message(client: TestClient) -> None:
    body = {
        "event": "MESSAGES_UPSERT",
        "instance": INSTANCE,
        "data": {
            "key": {
                "remoteJid": "5511999990001@s.whatsapp.net",
                "fromMe": True,
                "id": "OUTBOUND123",
            },
            "message": {"conversation": "mensagem enviada por nos"},
        },
    }
    resp = client.post("/webhooks/whatsapp", json=body, headers=_token_headers())
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "outbound"


def test_webhook_skips_non_text_message(client: TestClient) -> None:
    body = {
        "event": "MESSAGES_UPSERT",
        "instance": INSTANCE,
        "data": {
            "key": {
                "remoteJid": "5511@s.whatsapp.net",
                "fromMe": False,
                "id": "STICKERABC",
            },
            "message": {
                "stickerMessage": {"fileSha256": "abc"},
            },
        },
    }
    resp = client.post("/webhooks/whatsapp", json=body, headers=_token_headers())
    assert resp.status_code == 200
    assert resp.json()["skipped"] == "no_text"


# ---------------------------------------------------------------------------
# Evento QRCODE_UPDATED
# ---------------------------------------------------------------------------

def test_webhook_stores_qr_on_qrcode_event(app_client) -> None:
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)

    resp = c.post("/webhooks/whatsapp", json=QRCODE_BODY, headers=_token_headers())

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert '"qrcode"' in call_args[1]


def test_webhook_handles_qrcode_without_pool() -> None:
    """Com db_pool = None o endpoint deve responder 200 sem travar."""
    _setup_webhook_token()
    app = create_app()
    with TestClient(app) as c:
        resp = c.post("/webhooks/whatsapp", json=QRCODE_BODY, headers=_token_headers())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Evento CONNECTION_UPDATE
# ---------------------------------------------------------------------------

def test_webhook_marks_connected_on_open_state(app_client) -> None:
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)

    resp = c.post("/webhooks/whatsapp", json=CONNECTION_CONNECTED_BODY, headers=_token_headers())

    assert resp.status_code == 200
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "connected" in sql


def test_webhook_marks_pending_on_close_state(app_client) -> None:
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)

    resp = c.post("/webhooks/whatsapp", json=CONNECTION_DISCONNECTED_BODY, headers=_token_headers())

    assert resp.status_code == 200
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "pending" in sql


# ---------------------------------------------------------------------------
# Pipeline de mensagem inbound
# ---------------------------------------------------------------------------

def test_webhook_returns_tenant_none_when_not_found(app_client) -> None:
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)
    conn.fetchrow = AsyncMock(return_value=None)

    resp = c.post("/webhooks/whatsapp", json=INBOUND_MESSAGE_BODY, headers=_token_headers())

    assert resp.status_code == 200
    assert resp.json()["tenant"] is None


def test_webhook_enqueues_celery_task_for_valid_message(app_client) -> None:
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": "tenant-uuid-001"},
        {"id": "conv-uuid-001"},
        {"opted_out": False},
        {"subscription_status": "active", "trial_ends_at": None},
    ])

    with patch("src.worker.tasks.process_whatsapp_message.delay") as mock_delay:
        resp = c.post("/webhooks/whatsapp", json=INBOUND_MESSAGE_BODY, headers=_token_headers())

    assert resp.status_code == 200
    assert resp.json().get("queued") is True
    mock_delay.assert_called_once()
    kwargs = mock_delay.call_args.kwargs
    assert kwargs["tenant_id"] == "tenant-uuid-001"
    assert kwargs["contact_phone"] == "5511999990001"
    assert "Quero agendar" in kwargs["user_message"]
    assert kwargs["instance_name"] == INSTANCE


# ---------------------------------------------------------------------------
# @lid resolution (privacy-mode WhatsApp accounts)
# ---------------------------------------------------------------------------

LID_INBOUND_BODY: dict[str, Any] = {
    "event": "MESSAGES_UPSERT",
    "instance": INSTANCE,
    "data": {
        "key": {
            # Masked privacy-mode JID — the digits BEFORE the colon are an
            # opaque WhatsApp internal id, not a phone. The sidecar caches
            # the real phone keyed by `id` so we can recover it here.
            "remoteJid": "265884312559697:56@lid",
            "fromMe": False,
            "id": "3EB0C8ADEC0C8974F7E361",
        },
        "message": {"conversation": "Oi, qual o horario?"},
        "pushName": "lorenzo",
    },
}


def test_webhook_resolves_lid_phone_before_enqueue(app_client) -> None:
    """When the inbound JID is @lid and the sidecar has cached the real
    phone, the Celery task must receive the resolved number, not the
    masked digits.
    """
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": "tenant-uuid-001"},
        {"id": "conv-uuid-001"},
        {"opted_out": False},
        {"subscription_status": "active", "trial_ends_at": None},
    ])

    with patch(
        "src.api.webhooks.whatsapp.resolve_lid_phone",
        new=AsyncMock(return_value="555191079110"),
    ) as mock_resolve, patch(
        "src.worker.tasks.process_whatsapp_message.delay"
    ) as mock_delay:
        resp = c.post("/webhooks/whatsapp", json=LID_INBOUND_BODY, headers=_token_headers())

    assert resp.status_code == 200
    assert resp.json().get("queued") is True
    mock_resolve.assert_awaited_once_with("3EB0C8ADEC0C8974F7E361")
    kwargs = mock_delay.call_args.kwargs
    # The resolved phone, not the masked "265884312559697:56".
    assert kwargs["contact_phone"] == "555191079110"


def test_webhook_falls_through_when_lid_resolution_misses(app_client) -> None:
    """If the sidecar hasn't cached the JID yet (race) the webhook must
    NOT drop the message — it queues with whatever contact_phone the
    provider gave (so the inbound is still persisted and the gap shows
    up in logs).
    """
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": "tenant-uuid-001"},
        {"id": "conv-uuid-001"},
        {"opted_out": False},
        {"subscription_status": "active", "trial_ends_at": None},
    ])

    with patch(
        "src.api.webhooks.whatsapp.resolve_lid_phone",
        new=AsyncMock(return_value=None),
    ), patch(
        "src.worker.tasks.process_whatsapp_message.delay"
    ) as mock_delay:
        resp = c.post("/webhooks/whatsapp", json=LID_INBOUND_BODY, headers=_token_headers())

    assert resp.status_code == 200
    assert resp.json().get("queued") is True
    kwargs = mock_delay.call_args.kwargs
    # parse_inbound_message uses jid.split("@")[0] -> "265884312559697:56".
    assert kwargs["contact_phone"] == "265884312559697:56"


def test_webhook_skips_lid_lookup_for_regular_phone(app_client) -> None:
    """Pre-privacy WA accounts arrive with @s.whatsapp.net JIDs. The
    resolver MUST NOT be called for those — every webhook hit doing a
    Redis round trip is wasted latency for the common path.
    """
    _app, pool, c = app_client
    conn = _make_fresh_conn(pool)
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": "tenant-uuid-001"},
        {"id": "conv-uuid-001"},
        {"opted_out": False},
        {"subscription_status": "active", "trial_ends_at": None},
    ])

    with patch(
        "src.api.webhooks.whatsapp.resolve_lid_phone",
        new=AsyncMock(return_value="never-called"),
    ) as mock_resolve, patch(
        "src.worker.tasks.process_whatsapp_message.delay"
    ):
        resp = c.post("/webhooks/whatsapp", json=INBOUND_MESSAGE_BODY, headers=_token_headers())

    assert resp.status_code == 200
    mock_resolve.assert_not_awaited()
