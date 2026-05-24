"""WhatsApp webhook receiver -- provider-agnostic.

This handler talks to a WhatsAppProvider (Evolution, Stub, ...) to:

  * verify webhook authenticity
  * classify the event (QR / connection / inbound message)
  * normalize the payload into a uniform shape

The DB-side bookkeeping (idempotency, tenant resolution, conversation
upsert, message persistence, Celery dispatch) is provider-agnostic and
lives below.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.core.config import get_settings
from src.core.logging import get_logger
from src.integrations.whatsapp import get_whatsapp_provider
from src.worker.tasks import process_whatsapp_message

logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])
settings = get_settings()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _record_webhook_event(
    conn: asyncpg.Connection,
    source: str,
    event_type: str,
    external_id: str,
    payload: dict,
    tenant_id: str | None,
) -> bool:
    """Insert webhook_events row. Returns False on duplicate."""
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
    """Return tenant_id for a non-revoked WhatsApp instance, or None."""
    row = await conn.fetchrow(
        """
        SELECT tenant_id::text
        FROM   integrations
        WHERE  kind        = 'whatsapp'
          AND  external_id = $1
          AND  status      != 'revoked'
        LIMIT 1
        """,
        instance_name,
    )
    return row["tenant_id"] if row else None


async def _upsert_conversation(
    conn: asyncpg.Connection, tenant_id: str, contact_phone: str, contact_name: str | None
) -> str:
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


def _classify_messages_skip_reason(body: dict[str, Any]) -> str:
    """When parse_inbound_message returns None, figure out what to report.

    Provider-shape-aware heuristic so we can keep telling the platform
    whether the message was outbound, sticker-only, etc.
    """
    data = body.get("data", {}) if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        return "invalid_data"
    key = data.get("key") or {}
    if isinstance(key, dict) and key.get("fromMe"):
        return "outbound"
    return "no_text"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/whatsapp")
@router.post("/whatsapp/{event_path:path}")
async def receive_whatsapp_event(request: Request, event_path: str = "") -> JSONResponse:
    """Handle inbound WhatsApp provider events.

    Response shapes (kept stable for partner retries):
      200 {"ok": True}                                 -- QR / connection accepted
      200 {"ok": True, "skipped": "<reason>"}          -- event ignored
      200 {"ok": True, "duplicate": True}              -- replay
      200 {"ok": True, "tenant": None}                 -- unknown instance
      200 {"ok": True, "queued": True}                 -- handed to worker
      400                                              -- invalid JSON
      401                                              -- bad webhook token
    """
    pool = getattr(request.app.state, "db_pool", None)
    provider = get_whatsapp_provider()

    raw = await request.body()
    try:
        parsed: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json") from exc

    body = parsed if isinstance(parsed, dict) else {}
    raw_event = str(body.get("event", ""))
    instance_name = str(body.get("instance", ""))

    if not provider.verify_webhook_auth(dict(request.headers)):
        logger.warning("webhook.auth_failed", evo_event=raw_event, instance=instance_name)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

    event_type = provider.parse_event_type(body)

    logger.info(
        "webhook.hit",
        evo_event=raw_event,
        normalized=event_type,
        instance=instance_name,
        provider=provider.name,
        pool=pool is not None,
    )

    # -- QR code update --------------------------------------------------
    if event_type == "qrcode_updated":
        qr_b64 = provider.parse_qrcode(body)
        if qr_b64 and pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE integrations
                       SET config = COALESCE(config, '{}'::jsonb) || $1::jsonb
                     WHERE kind        = 'whatsapp'
                       AND external_id = $2
                       AND status     != 'revoked'
                    """,
                    json.dumps({"qrcode": qr_b64}),
                    instance_name,
                )
            logger.info("webhook.qr_stored", instance=instance_name, qr_len=len(qr_b64))
        return JSONResponse({"ok": True})

    # -- Connection state update -----------------------------------------
    if event_type == "connection_update":
        update = provider.parse_connection_update(body)
        logger.info("webhook.connection_update", instance=instance_name, state=update.state)

        if not pool:
            return JSONResponse({"ok": True})

        if update.state == "open":
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
        elif update.state in ("close", "refused"):
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
            logger.info(
                "webhook.whatsapp_disconnected",
                instance=instance_name,
                state=update.state,
            )

        return JSONResponse({"ok": True})

    # -- Anything else -> normalize as inbound message -------------------
    if event_type != "messages_upsert":
        logger.info("webhook.skipped_event", evo_event=raw_event, instance=instance_name)
        return JSONResponse({"ok": True, "skipped": raw_event})

    inbound = provider.parse_inbound_message(body)
    if inbound is None:
        skip_reason = _classify_messages_skip_reason(body)
        return JSONResponse({"ok": True, "skipped": skip_reason})

    logger.info(
        "webhook.messages_upsert",
        instance=instance_name,
        pool=pool is not None,
        contact_phone=inbound.contact_phone,
    )

    if pool is None:
        logger.warning("webhook.no_pool", instance=instance_name)
        return JSONResponse({"ok": True, "queued": False})

    async with pool.acquire() as conn:
        is_new = await _record_webhook_event(
            conn,
            source=provider.name,
            event_type=raw_event or "messages_upsert",
            external_id=inbound.provider_message_id,
            payload=body,
            tenant_id=None,
        )
        if not is_new:
            logger.info("webhook.duplicate", message_id=inbound.provider_message_id)
            return JSONResponse({"ok": True, "duplicate": True})

        tenant_id = await _resolve_tenant(conn, instance_name)
        if not tenant_id:
            logger.warning("webhook.tenant_not_found", instance=instance_name)
            return JSONResponse({"ok": True, "tenant": None})

        await conn.execute(
            "UPDATE webhook_events SET tenant_id = $1 WHERE source = $2 AND external_id = $3",
            tenant_id,
            provider.name,
            inbound.provider_message_id,
        )

        conversation_id = await _upsert_conversation(
            conn, tenant_id, inbound.contact_phone, inbound.contact_name
        )
        await _insert_inbound_message(
            conn, tenant_id, conversation_id, inbound.provider_message_id, inbound.text
        )

    # Honor opt-out without re-running the agent.
    async with pool.acquire() as conn:
        opted_row = await conn.fetchrow(
            "SELECT opted_out FROM conversations WHERE id = $1::uuid",
            conversation_id,
        )
    if opted_row and opted_row["opted_out"]:
        logger.info("webhook.opted_out_skipped", conversation_id=conversation_id)
        return JSONResponse({"ok": True, "skipped": "opted_out"})

    # Subscription gate: trial expired / suspended tenants get a polite
    # pt-BR message and skip the Celery dispatch. The agent never sees
    # the turn, so we don't pay LLM tokens for a non-paying customer.
    # See ``core/billing_gate.py`` for the decision matrix.
    from src.core.billing_gate import check_subscription  # noqa: PLC0415
    from src.integrations.whatsapp import get_whatsapp_provider as _gp  # noqa: PLC0415

    gate = await check_subscription(pool, tenant_id)
    if not gate.allowed:
        logger.info(
            "webhook.billing_blocked",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            status=gate.status,
            reason=gate.reason,
        )
        # Best-effort reply so the customer doesn't sit in dead air.
        # Failure here is non-fatal — we already accepted the webhook.
        try:
            await _gp().send_text(
                instance_name=instance_name,
                phone=inbound.contact_phone,
                text=gate.reply_to_customer,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "webhook.billing_block_reply_failed",
                instance=instance_name,
                error=str(exc),
            )
        return JSONResponse(
            {"ok": True, "skipped": "billing", "billing_status": gate.status}
        )

    process_whatsapp_message.delay(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_phone=inbound.contact_phone,
        user_message=inbound.text,
        instance_name=instance_name,
    )

    logger.info("webhook.queued", tenant_id=tenant_id, conversation_id=conversation_id)
    return JSONResponse({"ok": True, "queued": True})
