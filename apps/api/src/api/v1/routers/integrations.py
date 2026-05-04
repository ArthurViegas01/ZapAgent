"""REST router — /v1/tenants/{tenant_id}/integrations

Endpoints:
  GET    /v1/tenants/{tenant_id}/integrations            → list all integrations
  POST   /v1/tenants/{tenant_id}/integrations/whatsapp   → create/bootstrap Evolution instance
  DELETE /v1/tenants/{tenant_id}/integrations/whatsapp   → disconnect instance
  GET    /v1/tenants/{tenant_id}/integrations/whatsapp/status → poll QR / connection status
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from ....core.config import get_settings
from ....core.evolution_qr import evolution_qr_diagnose, evolution_qr_to_data_url
from ....core.logging import get_logger
from ..dependencies import TenantContext, require_owner_or_admin, require_tenant

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tenants/{tenant_id}/integrations", tags=["integrations"])
_settings = get_settings()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class IntegrationOut(BaseModel):
    id: str
    kind: str
    external_id: str | None
    status: str
    config: dict
    created_at: datetime


class WhatsappConnectOut(BaseModel):
    instance_name: str
    qrcode: str
    status: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[IntegrationOut])
async def list_integrations(
    ctx: TenantContext = Depends(require_tenant),
) -> list[IntegrationOut]:
    async with ctx.conn() as conn:
        rows = await conn.fetch(
            "SELECT id::text, kind, external_id, status, config, created_at "
            "FROM integrations WHERE tenant_id = $1::uuid ORDER BY created_at",
            ctx.tenant_id,
        )
    return [
        IntegrationOut(
            id=r["id"],
            kind=r["kind"],
            external_id=r["external_id"],
            status=r["status"],
            config=dict(r["config"] or {}),
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def _fetch_and_store_qr(pool: object, instance_name: str, tenant_id: str) -> None:
    """Background task: wait for Baileys to initialise, then pull QR directly.

    Evolution generates the QR ~4-6 s after instance creation. We call
    GET /instance/connect/{name} ONCE (not in a loop) to retrieve it and
    store it in integrations.config.qrcode so the frontend poller can display it.
    Calling this endpoint once is safe; calling it repeatedly is what restarts Baileys.
    """
    import asyncio  # noqa: PLC0415
    import json as _json  # noqa: PLC0415
    import asyncpg  # noqa: PLC0415

    # Baileys often returns only {"count": 0} from GET /connect for many seconds;
    # give it time before polling (aggressive polling can keep count at 0).
    await asyncio.sleep(15)

    evo_url = _settings.evolution_api_url
    evo_key = _settings.evolution_api_key
    logger.info(
        "integrations.qr_fetch_task_start",
        instance=instance_name,
        tenant_suffix=tenant_id[-8:] if tenant_id else "",
        evolution_base=evo_url,
        evolution_key_configured=bool(evo_key),
    )

    # Check whether the webhook already stored a QR — skip if so.
    try:
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            row = await conn.fetchrow(
                "SELECT config FROM integrations "
                "WHERE kind = 'whatsapp' AND external_id = $1 AND status != 'revoked'",
                instance_name,
            )
        if row:
            import json as _json_check  # noqa: PLC0415
            cfg = row["config"] or {}
            if isinstance(cfg, str):
                cfg = _json_check.loads(cfg)
            existing_qr = cfg.get("qrcode") or ""
            if existing_qr:
                logger.info(
                    "integrations.qr_already_stored",
                    instance=instance_name,
                    existing_qr_len=len(str(existing_qr)),
                )
                return
    except Exception as exc:  # noqa: BLE001
        logger.warning("integrations.qr_check_failed", error=str(exc))

    # Fetch QR directly from Evolution — retry up to 4 times.
    # Evolution v2 (latest) returns the QR from GET /instance/connect/{name}.
    # We log the full raw response on the first attempt so we can see the
    # exact shape if the key names differ between Evolution versions.
    qr_b64 = ""
    for attempt in range(5):
        if attempt > 0:
            await asyncio.sleep(10)  # wait between retries

        try:
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.get(
                    f"{evo_url}/instance/connect/{instance_name}",
                    headers={"apikey": evo_key},
                )

            if resp.is_success:
                data = resp.json()
                diag_root = evolution_qr_diagnose(data if isinstance(data, dict) else None)
                inst = data.get("instance") if isinstance(data, dict) and isinstance(data.get("instance"), dict) else None
                diag_inst = evolution_qr_diagnose(inst) if inst else None
                # Log raw response on first attempt to diagnose key name.
                if attempt == 0:
                    logger.info(
                        "integrations.qr_response_shape",
                        instance=instance_name,
                        keys=list(data.keys()) if isinstance(data, dict) else "not_dict",
                        body_preview=str(data)[:400],
                        diagnose_root=diag_root,
                        diagnose_instance=diag_inst,
                    )
                if diag_root.get("top_keys") == ["count"] and diag_root.get("count") == 0:
                    logger.info(
                        "integrations.qr_connect_placeholder_only",
                        instance=instance_name,
                        attempt=attempt + 1,
                    )
                # Evolution v2: GET /instance/connect often returns the raw QrCode
                # object at the root (pairingCode, code, count) with no base64, or
                # wrapped as { "qrcode": {...}, "instance": {...} }.
                qr_b64 = evolution_qr_to_data_url(data if isinstance(data, dict) else None)
                if not qr_b64 and inst:
                    qr_b64 = evolution_qr_to_data_url(inst)
                logger.info(
                    "integrations.qr_fetch_attempt",
                    instance=instance_name,
                    attempt=attempt + 1,
                    has_qr=bool(qr_b64),
                    status=resp.status_code,
                    parsed_len=len(qr_b64) if qr_b64 else 0,
                    tried_instance_nested=bool(inst),
                )
                if qr_b64:
                    break
            else:
                logger.warning(
                    "integrations.qr_fetch_bad_status",
                    instance=instance_name,
                    attempt=attempt + 1,
                    status=resp.status_code,
                    body=resp.text[:300],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "integrations.qr_fetch_failed",
                instance=instance_name,
                attempt=attempt + 1,
                error=str(exc),
            )

    if not qr_b64:
        logger.warning(
            "integrations.qr_not_obtained",
            instance=instance_name,
            hint="check_evolution_qr_response_shape_and_webhook_qrcode_updated",
        )
        return

    # Store QR in DB.
    try:
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(
                """
                UPDATE integrations
                   SET config = COALESCE(config, '{}'::jsonb) || $1::jsonb
                 WHERE kind        = 'whatsapp'
                   AND external_id = $2
                   AND status     != 'revoked'
                """,
                _json.dumps({"qrcode": qr_b64}),
                instance_name,
            )
        logger.info("integrations.qr_stored_direct", instance=instance_name, qr_len=len(qr_b64))
    except Exception as exc:  # noqa: BLE001
        logger.warning("integrations.qr_store_failed", error=str(exc))


@router.post("/whatsapp", response_model=WhatsappConnectOut, status_code=status.HTTP_201_CREATED)
async def connect_whatsapp(
    background_tasks: BackgroundTasks,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> WhatsappConnectOut:
    """Bootstrap an Evolution API instance for WhatsApp pairing.

    Flow:
      1. Delete any EXISTING instance (old name stored in DB) from Evolution.
      2. Generate a FRESH instance name — fresh name = no stale session in
         Evolution's Redis/Postgres, so Baileys starts clean and generates a QR.
      3. Create the new instance; return immediately with status=pending.
      4. Background task waits 8 s then fetches QR directly via GET /instance/connect
         (single call only — loops restart Baileys).
      5. The qrcode.updated webhook also stores the QR if it fires.
      6. Frontend polls /whatsapp/status every 4 s; QR appears within ~12 s.
    """
    import asyncio  # noqa: PLC0415
    import secrets  # noqa: PLC0415

    # Fresh random suffix on every connect prevents Baileys from loading stale
    # WhatsApp session credentials cached in Evolution's Redis (db 3).
    # Without this, Evolution finds the old session, WhatsApp rejects it,
    # and Baileys enters a LOGOUT → restart loop, never reaching QR generation.
    instance_suffix = secrets.token_hex(4)  # 8 random hex chars
    instance_name = f"za-{ctx.tenant_id[:6]}-{instance_suffix}"
    evo_url = _settings.evolution_api_url
    evo_key = _settings.evolution_api_key
    plain_headers = {"apikey": evo_key}
    json_headers = {"apikey": evo_key, "Content-Type": "application/json"}

    # Look up OLD instance name so we can clean it up first.
    old_instance_name: str | None = None
    async with ctx.conn() as conn:
        old_row = await conn.fetchrow(
            "SELECT external_id FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' AND status != 'revoked' LIMIT 1",
            ctx.tenant_id,
        )
    if old_row:
        old_instance_name = old_row["external_id"]

    qr_from_create = ""

    logger.info(
        "integrations.whatsapp_connect_start",
        tenant_id_suffix=ctx.tenant_id[-8:],
        user_id_suffix=ctx.user_id[-8:] if len(ctx.user_id) > 8 else ctx.user_id,
        role=ctx.role,
        instance=instance_name,
        had_previous_instance=old_instance_name is not None,
        evolution_base=evo_url,
        evolution_key_configured=bool(evo_key),
    )

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            # Step 1: delete OLD instance (different name) so Evolution cleans it up.
            if old_instance_name:
                try:
                    del_resp = await client.delete(
                        f"{evo_url}/instance/delete/{old_instance_name}",
                        headers=plain_headers,
                    )
                    logger.info("evolution.old_instance_deleted",
                                old=old_instance_name, status=del_resp.status_code)
                    await asyncio.sleep(2)  # let Evolution finish cleanup
                except Exception as exc:  # noqa: BLE001
                    logger.debug("evolution.delete_skipped", error=str(exc))

            # Step 2: create fresh instance — qrcode:true starts Baileys immediately.
            resp = await client.post(
                f"{evo_url}/instance/create",
                json={
                    "instanceName": instance_name,
                    "integration": "WHATSAPP-BAILEYS",
                    "qrcode": True,
                },
                headers=json_headers,
            )
            resp.raise_for_status()
            created: dict = {}
            if resp.content:
                try:
                    parsed = resp.json()
                    if isinstance(parsed, dict):
                        created = parsed
                except Exception:  # noqa: BLE001
                    created = {}
            q_raw = created.get("qrcode") if isinstance(created, dict) else None
            if isinstance(q_raw, dict):
                qr_from_create = evolution_qr_to_data_url(q_raw)
            elif isinstance(q_raw, str) and q_raw.strip():
                qr_from_create = evolution_qr_to_data_url({"base64": q_raw})
            diag_create = evolution_qr_diagnose(q_raw if isinstance(q_raw, dict) else None)
            logger.info(
                "evolution.instance_created",
                instance=instance_name,
                status=resp.status_code,
                create_top_keys=sorted(created.keys()) if created else [],
                qrcode_diagnose=diag_create,
                qr_from_create_len=len(qr_from_create),
            )

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "integrations.whatsapp_connect_evolution_http_error",
            instance=instance_name,
            status=exc.response.status_code,
            body_preview=exc.response.text[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Evolution API error: {exc.response.text}",
        ) from exc

    # Revoke old records + insert fresh one. Since instance_name is always new,
    # ON CONFLICT never fires — we revoke old rows first instead.
    async with ctx.conn() as conn:
        await conn.execute(
            "UPDATE integrations SET status = 'revoked' "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' AND status != 'revoked'",
            ctx.tenant_id,
        )
        await conn.execute(
            """
            INSERT INTO integrations (tenant_id, kind, external_id, status, config)
            VALUES ($1::uuid, 'whatsapp', $2, 'pending', '{"qrcode":""}'::jsonb)
            """,
            ctx.tenant_id,
            instance_name,
        )
        if qr_from_create:
            await conn.execute(
                """
                UPDATE integrations
                   SET config = COALESCE(config, '{}'::jsonb) || $1::jsonb
                 WHERE tenant_id = $2::uuid AND kind = 'whatsapp'
                   AND external_id = $3 AND status != 'revoked'
                """,
                json.dumps({"qrcode": qr_from_create}),
                ctx.tenant_id,
                instance_name,
            )
            logger.info(
                "integrations.qr_from_create_stored",
                instance=instance_name,
                qr_len=len(qr_from_create),
            )

    # Schedule background QR fetch as a safety net (waits then polls /connect).
    background_tasks.add_task(_fetch_and_store_qr, ctx.pool, instance_name, ctx.tenant_id)

    logger.info(
        "integrations.whatsapp_connect_enqueued",
        instance=instance_name,
        tenant_id_suffix=ctx.tenant_id[-8:],
        background_qr_fetch=True,
        returned_inline_qr=bool(qr_from_create),
    )
    return WhatsappConnectOut(
        instance_name=instance_name,
        qrcode=qr_from_create,
        status="pending",
    )


@router.get("/whatsapp/status")
async def whatsapp_status(
    ctx: TenantContext = Depends(require_tenant),
) -> dict:
    """Return WhatsApp connection status.

    Uses ONLY /instance/connectionState — never /instance/connect.
    Calling /instance/connect during polling restarts Baileys and
    prevents QR code generation.
    The QR code comes from integrations.config.qrcode (stored by the
    qrcode.updated webhook handler).
    """
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "SELECT external_id, status, config FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' "
            "ORDER BY created_at DESC LIMIT 1",
            ctx.tenant_id,
        )
    if not row:
        logger.info(
            "integrations.whatsapp_status",
            phase="not_configured",
            tenant_suffix=ctx.tenant_id[-8:],
        )
        return {"status": "not_configured"}

    instance_name: str = row["external_id"] or ""
    db_status: str = row["status"]
    config = row["config"] or {}
    if isinstance(config, str):
        import json
        config = json.loads(config)
    qrcode: str = config.get("qrcode", "")

    if not instance_name:
        return {"status": db_status, "qrcode": qrcode}

    # Check live connection state (safe to poll — read-only).
    evo_state = ""
    state_http: int | None = None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            state_resp = await client.get(
                f"{_settings.evolution_api_url}/instance/connectionState/{instance_name}",
                headers={"apikey": _settings.evolution_api_key},
            )
            state_http = state_resp.status_code
            if state_resp.is_success:
                evo_state = state_resp.json().get("instance", {}).get("state", "")
            else:
                logger.warning(
                    "integrations.whatsapp_status_connection_state_http",
                    instance=instance_name,
                    status=state_http,
                    body_preview=state_resp.text[:200],
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "integrations.whatsapp_status_connection_state_error",
            instance=instance_name,
            error=str(exc),
        )

    new_status = "connected" if evo_state == "open" else db_status

    logger.info(
        "integrations.whatsapp_status",
        phase="poll",
        instance=instance_name,
        db_status=db_status,
        evo_state=evo_state or "(empty)",
        new_status=new_status,
        state_http=state_http,
        qrcode_len=len(qrcode) if qrcode else 0,
        tenant_suffix=ctx.tenant_id[-8:],
    )

    if new_status != db_status:
        async with ctx.conn() as conn:
            await conn.execute(
                "UPDATE integrations SET status = $1 "
                "WHERE tenant_id = $2::uuid AND kind = 'whatsapp' AND external_id = $3",
                new_status,
                ctx.tenant_id,
                instance_name,
            )

    return {
        "status": new_status,
        "instance_name": instance_name,
        "qrcode": qrcode if new_status != "connected" else "",
    }


@router.delete("/whatsapp", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_whatsapp(
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> None:
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "SELECT external_id FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' AND status != 'revoked' LIMIT 1",
            ctx.tenant_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active WhatsApp integration.")

    instance_name = row["external_id"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{_settings.evolution_api_url}/instance/delete/{instance_name}",
                headers={"apikey": _settings.evolution_api_key},
            )
    except Exception:  # noqa: BLE001
        logger.warning("integrations.evo_delete_failed", instance=instance_name)

    async with ctx.conn() as conn:
        await conn.execute(
            "UPDATE integrations SET status = 'revoked' "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp'",
            ctx.tenant_id,
        )


# ---------------------------------------------------------------------------
# Google Calendar OAuth
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_SCOPES = "https://www.googleapis.com/auth/calendar.events"


@router.get("/google-calendar/oauth-start")
async def google_calendar_oauth_start(
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> dict:
    """Return the Google OAuth consent URL for the tenant to authorize."""
    import urllib.parse  # noqa: PLC0415

    cfg = get_settings()
    if not cfg.google_oauth_client_id:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Google OAuth not configured.")

    state_token = ctx.tenant_id  # sign in production; tenant_id is enough for MVP
    params = {
        "client_id": cfg.google_oauth_client_id,
        "redirect_uri": cfg.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
    }
    url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return {"oauth_url": url}


class GoogleCalendarCallbackIn(BaseModel):
    code: str
    state: str  # tenant_id echoed back


@router.post("/google-calendar/oauth-callback", status_code=status.HTTP_201_CREATED)
async def google_calendar_oauth_callback(
    body: GoogleCalendarCallbackIn,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> dict:
    """Exchange the OAuth code for tokens and persist the integration."""
    import json as _json  # noqa: PLC0415
    from datetime import timezone as _tz  # noqa: PLC0415

    cfg = get_settings()

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": body.code,
                    "client_id": cfg.google_oauth_client_id,
                    "client_secret": cfg.google_oauth_client_secret,
                    "redirect_uri": cfg.google_oauth_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google token exchange failed.") from exc

    now_ts = datetime.now(tz=_tz.utc).timestamp()
    secrets = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": now_ts + token_data.get("expires_in", 3600),
        "token_type": token_data.get("token_type", "Bearer"),
    }

    # Fetch the user's primary calendar id
    calendar_id = "primary"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cal_resp = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary",
                headers={"Authorization": f"Bearer {secrets['access_token']}"},
            )
            if cal_resp.status_code == 200:
                calendar_id = cal_resp.json().get("id", "primary")
    except Exception:  # noqa: BLE001
        pass

    async with ctx.conn() as conn:
        await conn.execute(
            """
            INSERT INTO integrations (tenant_id, kind, external_id, status, config, secrets)
            VALUES ($1::uuid, 'google_calendar', $2, 'connected', '{}'::jsonb, $3::jsonb)
            ON CONFLICT (tenant_id, kind, external_id)
            DO UPDATE SET status = 'connected', secrets = EXCLUDED.secrets, last_synced_at = NOW()
            """,
            ctx.tenant_id,
            calendar_id,
            _json.dumps(secrets),
        )

    logger.info("integrations.gcal_connected", tenant_id=ctx.tenant_id, calendar_id=calendar_id)
    return {"status": "connected", "calendar_id": calendar_id}


@router.delete("/google-calendar", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_google_calendar(
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> None:
    async with ctx.conn() as conn:
        await conn.execute(
            "UPDATE integrations SET status = 'revoked' "
            "WHERE tenant_id = $1::uuid AND kind = 'google_calendar'",
            ctx.tenant_id,
        )
