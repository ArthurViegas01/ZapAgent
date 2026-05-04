"""schedule_appointment - create a Google Calendar event.

Production path (requires db_pool in config + google_calendar integration):
  1. Load OAuth tokens from integrations.secrets
  2. Refresh the access token if expiring within 5 minutes
  3. Call Google Calendar events.insert
  4. Persist a row in appointments table
  5. Return confirmation message

Offline/test path (no pool): fabricates a deterministic id so downstream
code paths can be exercised without hitting the network.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from langchain_core.runnables import RunnableConfig

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState, AppointmentDraft

logger = get_logger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
TOKEN_REFRESH_BUFFER_SECS = 300  # refresh if expiring within 5 min


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _placeholder_draft(state: AgentState) -> AppointmentDraft:
    starts = datetime.now(tz=timezone.utc) + timedelta(days=1)
    ends = starts + timedelta(minutes=30)
    return AppointmentDraft(
        title="Atendimento - " + state.get("contact_phone", "cliente"),
        starts_at=starts.isoformat(),
        ends_at=ends.isoformat(),
        notes=state.get("user_message", ""),
    )


async def _load_gcal_integration(pool: Any, tenant_id: str) -> dict | None:
    """Return the google_calendar integration row or None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id::text, external_id, config, secrets "
            "FROM integrations "
            "WHERE tenant_id = $1::uuid AND kind = 'google_calendar' AND status = 'connected' "
            "LIMIT 1",
            tenant_id,
        )
    if not row:
        return None
    return {
        "id": row["id"],
        "calendar_id": row["external_id"] or "primary",
        "config": row["config"] or {},
        "secrets": row["secrets"] or {},
    }


async def _refresh_token_if_needed(
    pool: Any,
    integration_id: str,
    secrets: dict,
) -> str:
    """Return a valid access token, refreshing via OAuth if near expiry."""
    cfg = get_settings()
    access_token: str = secrets.get("access_token", "")
    expires_at: float = float(secrets.get("expires_at", 0))
    refresh_token: str = secrets.get("refresh_token", "")

    now_ts = datetime.now(tz=timezone.utc).timestamp()
    if expires_at - now_ts > TOKEN_REFRESH_BUFFER_SECS:
        return access_token

    # Need to refresh
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": cfg.google_oauth_client_id,
                "client_secret": cfg.google_oauth_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    new_access = token_data["access_token"]
    new_expires = now_ts + token_data.get("expires_in", 3600)

    secrets["access_token"] = new_access
    secrets["expires_at"] = new_expires

    # Persist updated token
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE integrations SET secrets = $1::jsonb, last_synced_at = NOW() "
            "WHERE id = $2::uuid",
            json.dumps(secrets),
            integration_id,
        )

    logger.info("schedule_appointment.token_refreshed", integration_id=integration_id)
    return new_access


async def _create_calendar_event(
    access_token: str,
    calendar_id: str,
    draft: AppointmentDraft,
    contact_phone: str,
) -> str:
    """Call Google Calendar API and return the event id."""
    event_body = {
        "summary": draft.get("title", "Atendimento ZapAgent"),
        "description": (
            "Agendado via ZapAgent.\n"
            "Contato: " + contact_phone + "\n"
            + (draft.get("notes") or "")
        ).strip(),
        "start": {"dateTime": draft.get("starts_at"), "timeZone": "America/Sao_Paulo"},
        "end": {"dateTime": draft.get("ends_at"), "timeZone": "America/Sao_Paulo"},
    }

    headers = {
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_CALENDAR_BASE + "/calendars/" + calendar_id + "/events",
            json=event_body,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["id"]


async def _persist_appointment(
    pool: Any,
    tenant_id: str,
    conversation_id: str,
    draft: AppointmentDraft,
    google_event_id: str,
    appointment_id: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO appointments "
            "(id, tenant_id, conversation_id, title, starts_at, ends_at, notes, google_event_id, status) "
            "VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::timestamptz, $6::timestamptz, $7, $8, 'confirmed')",
            appointment_id,
            tenant_id,
            conversation_id,
            draft.get("title", "Atendimento"),
            draft.get("starts_at"),
            draft.get("ends_at"),
            draft.get("notes", ""),
            google_event_id,
        )


def _format_confirmation(draft: AppointmentDraft) -> str:
    try:
        dt = datetime.fromisoformat(draft.get("starts_at", ""))
        # Format in pt-BR
        weekdays = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]
        day_name = weekdays[dt.weekday()]
        formatted = dt.strftime(f"{day_name}, %d/%m as %H:%M")
    except Exception:
        formatted = draft.get("starts_at", "")
    return (
        "Agendamento confirmado! "
        "Sua consulta esta marcada para " + formatted + ". "
        "Te aguardamos! Caso precise remarcar, e so nos avisar aqui."
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def schedule_appointment(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, object]:
    """Create a Google Calendar event and persist to appointments table."""
    draft = state.get("appointment") or _placeholder_draft(state)
    appointment_id = str(uuid.uuid4())

    configurable: dict[str, Any] = (config or {}).get("configurable", {})  # type: ignore[assignment]
    pool: Any | None = configurable.get("db_pool")
    tenant_id = state.get("tenant_id", "")
    conversation_id = state.get("conversation_id", "")
    contact_phone = state.get("contact_phone", "")

    if pool is None:
        # Offline/test mode
        logger.info("schedule_appointment.offline", tenant_id=tenant_id)
        return {
            "appointment": draft,
            "appointment_id": "apt_" + uuid.uuid4().hex[:12],
            "response": _format_confirmation(draft),
        }

    try:
        integration = await _load_gcal_integration(pool, tenant_id)

        if not integration:
            # No Google Calendar connected - fall back to DB-only appointment
            logger.warning("schedule_appointment.no_gcal_integration", tenant_id=tenant_id)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO appointments "
                    "(id, tenant_id, conversation_id, title, starts_at, ends_at, notes, status) "
                    "VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::timestamptz, $6::timestamptz, $7, 'pending')",
                    appointment_id,
                    tenant_id,
                    conversation_id,
                    draft.get("title", "Atendimento"),
                    draft.get("starts_at"),
                    draft.get("ends_at"),
                    draft.get("notes", ""),
                )
            return {
                "appointment": draft,
                "appointment_id": appointment_id,
                "response": _format_confirmation(draft),
            }

        access_token = await _refresh_token_if_needed(
            pool, integration["id"], integration["secrets"]
        )

        google_event_id = await _create_calendar_event(
            access_token,
            integration["calendar_id"],
            draft,
            contact_phone,
        )

        await _persist_appointment(
            pool, tenant_id, conversation_id, draft, google_event_id, appointment_id
        )

        logger.info(
            "schedule_appointment.done",
            tenant_id=tenant_id,
            appointment_id=appointment_id,
            google_event_id=google_event_id,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("schedule_appointment.failed", error=str(exc), tenant_id=tenant_id)
        # Still return a confirmation to the user - operator can handle manually
        return {
            "appointment": draft,
            "appointment_id": appointment_id,
            "response": _format_confirmation(draft),
        }

    return {
        "appointment": draft,
        "appointment_id": appointment_id,
        "response": _format_confirmation(draft),
    }
