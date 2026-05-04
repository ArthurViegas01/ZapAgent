"""Webhook receiver for Evolution API v2 WhatsApp events.

Evolution sends every event to WEBHOOK_GLOBAL_URL (configured as
http://api:8000/webhooks/whatsapp in docker-compose). Keep
WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=false so all events hit this path; per-event
URLs (e.g. …/connection-update) are not implemented here. This router:

  1. Validates the request via the Evolution API key header.
  2. Filters to only inbound text messages (messages.upsert, fromMe=false).
  3. Writes an idempotency record to webhook_events — duplicate retries are
     silently accepted (HTTP 200) without re-enqueuing.
  4. Resolves the tenant from the Evolution instance name stored in integrations.
  5. Upserts the conversation row and persists the inbound message.
  6. Enqueues process_whatsapp_message via Celery.
  7. Returns HTTP 200 immediately so Evolution does not retry.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.core.config import get_settings
from src.core.evolution_qr import evolution_qr_diagnose, evolution_qr_to_data_url
from src.core.logging import get_logger
from src.worker.tasks import process_whatsapp_message

logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _extract_text(data: dict[str, Any]) -> str | None:
    """Pull plain text from the many message sub-types Evolution sends."""
    msg = data.get("message") or {}
    return (
        msg.get("conversation")
        or msg.get("extendedTextMessage", {}).get("text")
        or None
    )


def _phone_from_jid(jid: str) -> str:
    """Strip @s.whatsapp.net / @g.us suffix → E.164-ish digits."""
    return jid.split("@")[0]


# ---------------------------------------------------------------------------
# DB helpers (run inside the request, pool from app.state)
# ---------------------------------------------------------------------------

async def _record_webhook_event(
    conn: asyncpg.Connection,
    source: str,
    event_type: str,
    external_id: str,
    payload: dict,
    tenant_id: str | None,
) -> bool:
    """Insert webhook_events row. Returns False if already exists (duplicate)."""
    try:
        await conn.execute(
            """
            INSERT INTO webhook_events
                (source, event_type, external_id, payload, tenant_id)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            source,
            event_type,
            external_id,
            json.dumps(payload),
            tenant_id,
        )
        return True
    except asyncpg.UniqueViolationError:
        return False


async def _resolve_tenant(conn: asyncpg.Connection, instance_name: str) -> str | None:
    """Return tenant_id for a connected Evolution instance, or None."""
    row = await conn.fetchrow(
        """
        SELECT tenant_id::text
        FROM   integrations
        WHERE  kind        = 'whatsapp'
          AND  external_id = $1
          AND  status      = 'connected'
        LIMIT 1
        """,
        instance_name,
    )
    return row["tenant_id"] if row else None


async def _upsert_conversation(
    conn: asyncpg.Connection, tenant_id: str, contact_phone: str, contact_name: str | None
) -> str:
    """Upsert conversation and return its UUID."""
    row = await conn.fetchrow(
        """
        INSERT INTO conversations (tenant_id, contact_phone, contact_name, last_message_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (tenant_id, contact_phone)
        DO UPDATE SET last_message_at = NOW(),
                      contact_name    = COALESCE(EXCLUDED.contact_name, conversations.contact_name)
        RETURNING id::text
        """,
        tenant_id,
        contact_phone,
        contact_name,
    )
    return row["id"]


async def _insert_inbound_message(
    conn: asyncpg.Connection,
    tenant_id: str,
    conversation_id: str,
    provider_message_id: str,
    content: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO messages
            (tenant_id, conversation_id, direction, provider_message_id, role, content)
        VALUES ($1, $2, 'inbound', $3, 'user', $4)
        ON CONFLICT (tenant_id, provider_message_id) DO NOTHING
        """,
        tenant_id,
        conversation_id,
        provider_message_id,
        content,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/whatsapp")
async def receive_whatsapp_event(request: Request) -> JSONResponse:
    """Handle inbound Evolution API webhook events."""

    pool = getattr(request.app.state, "db_pool", None)
    path = request.url.path

    raw = await request.body()
    try:
        parsed: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        logger.warning("webhook.invalid_json", path=path, raw_len=len(raw), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid json",
        ) from exc
    body = parsed if isinstance(parsed, dict) else {}
    event_peek = str(body.get("event", ""))
    instance_peek = str(body.get("instance", ""))
    api_key_header = request.headers.get("apikey", "")
    cfg_key = settings.evolution_api_key or ""
    # Always log hits (even on auth failure) so we can correlate Evolution logs ↔ API.
    logger.info(
        "webhook.hit",
        path=path,
        evolution_event=event_peek,
        evolution_instance=instance_peek,
        pool=pool is not None,
        apikey_header_len=len(api_key_header),
        apikey_configured_len=len(cfg_key),
    )

    # 1. Auth — Evolution sends global API key in the `apikey` header.
    evo_key_configured = bool(cfg_key)
    if cfg_key and api_key_header != cfg_key:
        logger.warning(
            "webhook.auth_failed",
            path=path,
            header_present=bool(api_key_header),
            header_len=len(api_key_header),
            evolution_key_configured=evo_key_configured,
            keys_match=False,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid apikey")

    event_type: str = body.get("event", "")
    instance_name: str = body.get("instance", "")
    data: dict[str, Any] = body.get("data", {})

    logger.info(
        "webhook.ingress",
        path=path,
        evolution_event=event_type,
        evolution_instance=instance_name,
        pool=pool is not None,
        body_keys=sorted(body.keys()) if isinstance(body, dict) else "not_dict",
    )

    # 2a. QR code delivered by Evolution — store in DB so the frontend can poll it.
    if event_type == "qrcode.updated":
        diag = evolution_qr_diagnose(data if isinstance(data, dict) else None)
        logger.info("webhook.qrcode_event", instance=instance_name, diagnose=diag)
        qr_base64: str = evolution_qr_to_data_url(data if isinstance(data, dict) else None)
        if not pool:
            logger.warning("webhook.qrcode_skipped_no_db_pool", instance=instance_name)
        elif not qr_base64:
            logger.warning(
                "webhook.qrcode_empty_after_parse",
                instance=instance_name,
                diagnose=diag,
            )
        if qr_base64 and pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE integrations
                       SET config = COALESCE(config, '{}'::jsonb) || $1::jsonb
                     WHERE kind        = 'whatsapp'
                       AND external_id = $2
                       AND status     != 'revoked'
                    """,
                    json.dumps({"qrcode": qr_base64}),
                    instance_name,
                )
            logger.info("webhook.qr_stored", instance=instance_name, qr_len=len(qr_base64))
        return JSONResponse({"ok": True})

    # 2b. Connection state update — mark integration as connected/disconnected.
    if event_type == "connection.update":
        state: str = data.get("state", "")
        status_reason = data.get("statusReason")
        logger.info(
            "webhook.connection_update",
            instance=instance_name,
            state=state,
            status_reason=status_reason,
            pool=pool is not None,
        )
        if state == "open" and pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE integrations
                       SET status = 'connected',
                           config = COALESCE(config, '{}'::jsonb) - 'qrcode'
                     WHERE kind        = 'whatsapp'
                       AND external_id = $1
                       AND status     != 'revoked'
                    """,
                    instance_name,
                )
            logger.info("webhook.whatsapp_connected", instance=instance_name)
        elif state in ("close", "refused") and pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE integrations
                       SET status = 'pending'
                     WHERE kind        = 'whatsapp'
                       AND external_id = $1
                       AND status      = 'connected'
                    """,
                    instance_name,
                )
            logger.info("webhook.whatsapp_disconnected", instance=instance_name, state=state)
        elif state == "connecting":
            logger.info(
                "webhook.connection_connecting",
                instance=instance_name,
                status_reason=status_reason,
            )
        return JSONResponse({"ok": True})

    # 2c. Only handle inbound text messages for the agent pipeline.
    if event_type != "messages.upsert":
        logger.info(
            "webhook.skipped_event",
            evolution_event=event_type,
            evolution_instance=instance_name,
        )
        return JSONResponse({"ok": True, "skipped": event_type})

    logger.info(
        "webhook.messages_upsert",
        instance=instance_name,
        pool=pool is not None,
    )
    key = data.get("key", {})
    if key.get("fromMe", True):
        return JSONResponse({"ok": True, "skipped": "outbound"})

    text = _extract_text(data)
    if not text:
        return JSONResponse({"ok": True, "skipped": "no_text"})

    provider_message_id: str = key.get("id", "")
    contact_jid: str = key.get("remoteJid", "")
    contact_phone = _phone_from_jid(contact_jid)
    contact_name: str | None = data.get("pushName") or None

    if pool is None:
        # No DB pool (offline / test mode) — still return 200.
        logger.warning("webhook.no_pool", instance=instance_name)
        return JSONResponse({"ok": True, "queued": False})

    async with pool.acquire() as conn:
        # 3. Idempotency — silently accept duplicates.
        is_new = await _record_webhook_event(
            conn,
            source="evolution",
            event_type=event_type,
            external_id=provider_message_id,
            payload=body,
            tenant_id=None,  # will update below once we have tenant_id
        )
        if not is_new:
            logger.info("webhook.duplicate", message_id=provider_message_id)
            return JSONResponse({"ok": True, "duplicate": True})

        # 4. Resolve tenant from instance name.
        tenant_id = await _resolve_tenant(conn, instance_name)
        if not tenant_id:
            logger.warning("webhook.tenant_not_found", instance=instance_name)
            return JSONResponse({"ok": True, "tenant": None})

        # Update webhook_events with resolved tenant_id.
        await conn.execute(
            "UPDATE webhook_events SET tenant_id = $1 WHERE source = 'evolution' AND external_id = $2",
            tenant_id,
            provider_message_id,
        )

        # 5. Upsert conversation + persist inbound message.
        conversation_id = await _upsert_conversation(conn, tenant_id, contact_phone, contact_name)
        await _insert_inbound_message(
            conn, tenant_id, conversation_id, provider_message_id, text
        )

    # 6. Skip opted-out contacts — no agent, no reply.
    async with pool.acquire() as conn:
        opted_row = await conn.fetchrow(
            "SELECT opted_out FROM conversations WHERE id = $1::uuid",
            conversation_id,
        )
    if opted_row and opted_row["opted_out"]:
        logger.info("webhook.opted_out_skipped", conversation_id=conversation_id)
        return JSONResponse({"ok": True, "skipped": "opted_out"})

    # 7. Enqueue Celery task (outside DB transaction — fire and forget).
    process_whatsapp_message.delay(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_phone=contact_phone,
        user_message=text,
        instance_name=instance_name,
    )

    logger.info(
        "webhook.queued",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_phone=contact_phone,
    )

    return JSONResponse({"ok": True, "queued": True})
