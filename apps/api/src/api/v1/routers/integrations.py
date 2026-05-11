"""REST router -- /v1/tenants/{tenant_id}/integrations

Endpoints (provider-agnostic; the underlying gateway is configured via
``WHATSAPP_PROVIDER`` -- evolution, stub, ...):

  GET    /v1/tenants/{tenant_id}/integrations            -> list integrations
  POST   /v1/tenants/{tenant_id}/integrations/whatsapp   -> create session
  DELETE /v1/tenants/{tenant_id}/integrations/whatsapp   -> revoke session
  GET    /v1/tenants/{tenant_id}/integrations/whatsapp/status -> poll QR/state

Plus Google Calendar OAuth (start/callback/delete).
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ....core.config import get_settings
from ....core.logging import get_logger
from ....integrations.whatsapp import get_whatsapp_provider
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
    provider: str


# ---------------------------------------------------------------------------
# Routes -- WhatsApp
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


@router.post("/whatsapp", response_model=WhatsappConnectOut, status_code=status.HTTP_201_CREATED)
async def connect_whatsapp(
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> WhatsappConnectOut:
    """Provision a new WhatsApp session at the configured provider.

    Flow:
      1. Revoke any existing session in DB and at the provider.
      2. Generate a fresh instance name (random suffix avoids stale Baileys
         sessions on Evolution / stale auth files on WPP).
      3. Provider creates the session and returns immediately (status=pending).
      4. Persist the integration row with empty qrcode.
      5. Return immediately — the QR arrives asynchronously via the
         qrcode.updated webhook, which stores it in the DB. The frontend
         discovers it by polling GET /whatsapp/status every few seconds.

    Why no poll loop here: calling GET /instance/connect on Evolution v2
    restarts the Baileys WebSocket handshake on each invocation, interrupting
    QR generation. The webhook-driven approach avoids that completely.
    """
    import secrets as _secrets

    provider = get_whatsapp_provider()
    instance_name = f"za-{ctx.tenant_id[:6]}-{_secrets.token_hex(4)}"

    logger.info(
        "integrations.whatsapp_connect_start",
        tenant_suffix=ctx.tenant_id[-8:],
        instance=instance_name,
        provider=provider.name,
    )

    # 1. Revoke old session at the provider.
    async with ctx.conn() as conn:
        old_row = await conn.fetchrow(
            "SELECT external_id FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' AND status != 'revoked' LIMIT 1",
            ctx.tenant_id,
        )
    if old_row and old_row["external_id"]:
        await provider.delete_session(old_row["external_id"])

    # 2 + 3. Create new session.
    try:
        session = await provider.create_session(instance_name)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "integrations.session_create_failed",
            http_status=exc.response.status_code,
            body=exc.response.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider error: {exc.response.text[:300]}",
        ) from exc

    qr_b64 = session.qrcode_data_url

    # 4. Persist DB row -- revoke previous, insert fresh.
    async with ctx.conn() as conn:
        await conn.execute(
            "UPDATE integrations SET status = 'revoked' "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' AND status != 'revoked'",
            ctx.tenant_id,
        )
        await conn.execute(
            "INSERT INTO integrations (tenant_id, kind, external_id, status, config) "
            "VALUES ($1::uuid, 'whatsapp', $2, 'pending', $3::jsonb)",
            ctx.tenant_id,
            instance_name,
            json.dumps({"qrcode": qr_b64, "provider": provider.name}),
        )

    return WhatsappConnectOut(
        instance_name=instance_name,
        qrcode=qr_b64,
        status="pending",
        provider=provider.name,
    )


@router.get("/whatsapp/status")
async def whatsapp_status(
    ctx: TenantContext = Depends(require_tenant),
) -> dict:
    """Return the latest known WhatsApp session state and QR (if pending)."""
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "SELECT external_id, status, config FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp' "
            "ORDER BY created_at DESC LIMIT 1",
            ctx.tenant_id,
        )
    if not row:
        return {"status": "not_configured"}

    instance_name: str = row["external_id"] or ""
    db_status: str = row["status"]
    config = row["config"] or {}
    if isinstance(config, str):
        config = json.loads(config)
    qrcode: str = config.get("qrcode", "")

    if not instance_name:
        return {"status": db_status, "qrcode": qrcode}

    provider = get_whatsapp_provider()
    session = await provider.get_session(instance_name)
    new_status = session.status

    logger.info(
        "integrations.whatsapp_status",
        instance=instance_name,
        db_status=db_status,
        provider=provider.name,
        provider_status=new_status,
        qrcode_len=len(qrcode) if qrcode else 0,
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

    # QR is written exclusively by the qrcode.updated webhook handler and read
    # here from the DB config column. get_session no longer fetches QR from the
    # provider (calling /instance/connect would restart the Baileys handshake).

    return {
        "status": new_status,
        "instance_name": instance_name,
        "qrcode": qrcode if new_status != "connected" else "",
        "provider": provider.name,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active WhatsApp integration.",
        )

    provider = get_whatsapp_provider()
    await provider.delete_session(row["external_id"])

    async with ctx.conn() as conn:
        await conn.execute(
            "UPDATE integrations SET status = 'revoked' "
            "WHERE tenant_id = $1::uuid AND kind = 'whatsapp'",
            ctx.tenant_id,
        )


# ---------------------------------------------------------------------------
# Routes -- Google Calendar OAuth
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_SCOPES = "https://www.googleapis.com/auth/calendar.events"


@router.get("/google-calendar/oauth-start")
async def google_calendar_oauth_start(
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> dict:
    """Return the Google OAuth consent URL."""
    import urllib.parse  # noqa: PLC0415

    cfg = get_settings()
    if not cfg.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured.",
        )

    params = {
        "client_id": cfg.google_oauth_client_id,
        "redirect_uri": cfg.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": ctx.tenant_id,
    }
    url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return {"oauth_url": url}


class GoogleCalendarCallbackIn(BaseModel):
    code: str
    state: str


@router.post("/google-calendar/oauth-callback", status_code=status.HTTP_201_CREATED)
async def google_calendar_oauth_callback(
    body: GoogleCalendarCallbackIn,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> dict:
    """Exchange OAuth code for tokens and persist the integration."""
    import json as _json  # noqa: PLC0415
    from datetime import timezone as _tz  # noqa: PLC0415

    cfg = get_settings()

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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token exchange failed.",
        ) from exc

    now_ts = datetime.now(tz=_tz.utc).timestamp()
    secrets_data = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": now_ts + token_data.get("expires_in", 3600),
        "token_type": token_data.get("token_type", "Bearer"),
    }

    calendar_id = "primary"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cal_resp = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary",
                headers={"Authorization": f"Bearer {secrets_data['access_token']}"},
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
            _json.dumps(secrets_data),
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
