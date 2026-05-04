"""REST router — /v1/tenants/{tenant_id}/conversations

Endpoints:
  GET  /v1/tenants/{tenant_id}/conversations                  → list (paginated, with filters)
  GET  /v1/tenants/{tenant_id}/conversations/{conv_id}        → detail
  GET  /v1/tenants/{tenant_id}/conversations/{conv_id}/messages → message history
  POST /v1/tenants/{tenant_id}/conversations/{conv_id}/close  → close conversation
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..dependencies import TenantContext, require_owner_or_admin, require_tenant

router = APIRouter(prefix="/v1/tenants/{tenant_id}/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConversationOut(BaseModel):
    id: str
    contact_phone: str
    contact_name: str | None
    status: str
    opted_out: bool
    last_message_at: datetime | None
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    direction: str
    role: str
    content: str
    intent: str | None
    confidence: float | None
    token_usage: dict | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    ctx: TenantContext = Depends(require_tenant),
    conv_status: str | None = Query(None, alias="status", description="active|handoff|closed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ConversationOut]:
    q = (
        "SELECT id::text, contact_phone, contact_name, status, opted_out, "
        "       last_message_at, created_at "
        "FROM conversations WHERE tenant_id = $1::uuid"
    )
    params: list = [ctx.tenant_id]
    idx = 2
    if conv_status:
        q += f" AND status = ${idx}"
        params.append(conv_status)
        idx += 1
    q += f" ORDER BY last_message_at DESC NULLS LAST LIMIT ${idx} OFFSET ${idx + 1}"
    params.extend([limit, offset])

    async with ctx.conn() as conn:
        rows = await conn.fetch(q, *params)
    return [ConversationOut(**dict(r)) for r in rows]


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: str,
    ctx: TenantContext = Depends(require_tenant),
) -> ConversationOut:
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "SELECT id::text, contact_phone, contact_name, status, opted_out, "
            "       last_message_at, created_at "
            "FROM conversations WHERE id = $1::uuid AND tenant_id = $2::uuid",
            conv_id,
            ctx.tenant_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return ConversationOut(**dict(row))


@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conv_id: str,
    ctx: TenantContext = Depends(require_tenant),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[MessageOut]:
    async with ctx.conn() as conn:
        # Verify conversation belongs to tenant.
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE id = $1::uuid AND tenant_id = $2::uuid",
            conv_id,
            ctx.tenant_id,
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

        rows = await conn.fetch(
            "SELECT id::text, direction, role, content, intent, "
            "       confidence::float, token_usage, created_at "
            "FROM messages WHERE conversation_id = $1::uuid "
            "ORDER BY created_at ASC LIMIT $2 OFFSET $3",
            conv_id,
            limit,
            offset,
        )
    return [MessageOut(**dict(r)) for r in rows]


@router.post("/{conv_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_conversation(
    conv_id: str,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> None:
    async with ctx.conn() as conn:
        result = await conn.execute(
            "UPDATE conversations SET status = 'closed' "
            "WHERE id = $1::uuid AND tenant_id = $2::uuid AND status != 'closed'",
            conv_id,
            ctx.tenant_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or already closed.",
        )
