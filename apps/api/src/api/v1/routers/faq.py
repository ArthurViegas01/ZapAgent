"""REST router — /v1/tenants/{tenant_id}/faq

Endpoints:
  GET    /v1/tenants/{tenant_id}/faq              → list FAQ items
  POST   /v1/tenants/{tenant_id}/faq              → create + re-index
  PATCH  /v1/tenants/{tenant_id}/faq/{faq_id}     → update + re-index
  DELETE /v1/tenants/{tenant_id}/faq/{faq_id}     → delete

Re-indexing (embedding generation) happens asynchronously after write so
the HTTP response is not blocked by the Voyage AI call.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ....core.config import get_settings
from ....core.logging import get_logger
from ..dependencies import TenantContext, require_owner_or_admin, require_tenant

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tenants/{tenant_id}/faq", tags=["faq"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FaqItemOut(BaseModel):
    id: str
    question: str
    answer: str
    is_active: bool
    created_at: datetime


class FaqCreate(BaseModel):
    question: str
    answer: str


class FaqUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

async def _reindex_faq(pool: Any, faq_id: str, tenant_id: str, text: str) -> None:
    """Generate embedding and persist to faq_items.embedding (best-effort)."""
    settings = get_settings()
    if not settings.voyage_api_key:
        return
    try:
        import voyageai  # noqa: PLC0415

        client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
        result = await client.embed(texts=[text], model=settings.voyage_model)
        embedding = result.embeddings[0]
        vec_lit = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                await conn.execute(
                    "UPDATE faq_items SET embedding = $1::vector WHERE id = $2::uuid",
                    vec_lit,
                    faq_id,
                )
        logger.info("faq.reindexed", faq_id=faq_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("faq.reindex_failed", faq_id=faq_id, error=str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[FaqItemOut])
async def list_faq(
    ctx: TenantContext = Depends(require_tenant),
    active_only: bool = False,
) -> list[FaqItemOut]:
    async with ctx.conn() as conn:
        q = (
            "SELECT id::text, question, answer, is_active, created_at "
            "FROM faq_items WHERE tenant_id = $1::uuid"
        )
        params: list = [ctx.tenant_id]
        if active_only:
            q += " AND is_active = TRUE"
        q += " ORDER BY created_at DESC"
        rows = await conn.fetch(q, *params)
    return [FaqItemOut(**dict(r)) for r in rows]


@router.post("", response_model=FaqItemOut, status_code=status.HTTP_201_CREATED)
async def create_faq(
    body: FaqCreate,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> FaqItemOut:
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question and answer are required.",
        )
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "INSERT INTO faq_items (tenant_id, question, answer) "
            "VALUES ($1::uuid, $2, $3) "
            "RETURNING id::text, question, answer, is_active, created_at",
            ctx.tenant_id,
            body.question.strip(),
            body.answer.strip(),
        )

    item = FaqItemOut(**dict(row))
    # Fire-and-forget re-indexing (don't await so HTTP response is fast).
    asyncio.create_task(
        _reindex_faq(ctx.pool, item.id, ctx.tenant_id, f"{body.question}\n{body.answer}")
    )
    return item


@router.patch("/{faq_id}", response_model=FaqItemOut)
async def update_faq(
    faq_id: str,
    body: FaqUpdate,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> FaqItemOut:
    updates: list[str] = []
    values: list = []
    idx = 1

    if body.question is not None:
        updates.append(f"question = ${idx}")
        values.append(body.question.strip())
        idx += 1
    if body.answer is not None:
        updates.append(f"answer = ${idx}")
        values.append(body.answer.strip())
        idx += 1
    if body.is_active is not None:
        updates.append(f"is_active = ${idx}")
        values.append(body.is_active)
        idx += 1

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing to update.",
        )

    values.extend([faq_id, ctx.tenant_id])
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            f"UPDATE faq_items SET {', '.join(updates)} "
            f"WHERE id = ${idx}::uuid AND tenant_id = ${idx + 1}::uuid "
            "RETURNING id::text, question, answer, is_active, created_at",
            *values,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ item not found.")

    item = FaqItemOut(**dict(row))
    if body.question or body.answer:
        q = body.question or item.question
        a = body.answer or item.answer
        asyncio.create_task(
            _reindex_faq(ctx.pool, item.id, ctx.tenant_id, f"{q}\n{a}")
        )
    return item


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: str,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> None:
    async with ctx.conn() as conn:
        result = await conn.execute(
            "DELETE FROM faq_items WHERE id = $1::uuid AND tenant_id = $2::uuid",
            faq_id,
            ctx.tenant_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ item not found.")
