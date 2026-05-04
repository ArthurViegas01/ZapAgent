"""REST router — /v1/tenants/{tenant_id}

Endpoints:
  GET    /v1/tenants/{tenant_id}         → fetch tenant details + settings
  PATCH  /v1/tenants/{tenant_id}         → update name / settings
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..dependencies import TenantContext, require_owner_or_admin, require_tenant

router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["tenants"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TenantOut(BaseModel):
    id: str
    slug: str
    name: str
    business_type: str | None
    plan: str
    status: str
    settings: dict


class TenantPatch(BaseModel):
    name: str | None = None
    settings: dict | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=TenantOut)
async def get_tenant(
    ctx: TenantContext = Depends(require_tenant),
) -> TenantOut:
    async with ctx.conn() as conn:
        row = await conn.fetchrow(
            "SELECT id::text, slug, name, business_type, plan, status, settings "
            "FROM tenants WHERE id = $1::uuid LIMIT 1",
            ctx.tenant_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return TenantOut(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        business_type=row["business_type"],
        plan=row["plan"],
        status=row["status"],
        settings=dict(row["settings"] or {}),
    )


@router.patch("", response_model=TenantOut)
async def patch_tenant(
    body: TenantPatch,
    ctx: TenantContext = Depends(require_owner_or_admin),
) -> TenantOut:
    async with ctx.conn() as conn:
        # Build SET clause dynamically.
        updates: list[str] = []
        values: list = []
        idx = 1

        if body.name is not None:
            updates.append(f"name = ${idx}")
            values.append(body.name)
            idx += 1

        if body.settings is not None:
            # Merge with existing settings using jsonb ||
            updates.append(f"settings = settings || ${idx}::jsonb")
            import json  # noqa: PLC0415
            values.append(json.dumps(body.settings))
            idx += 1

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nothing to update.",
            )

        values.append(ctx.tenant_id)
        row = await conn.fetchrow(
            f"UPDATE tenants SET {', '.join(updates)} "
            f"WHERE id = ${idx}::uuid "
            "RETURNING id::text, slug, name, business_type, plan, status, settings",
            *values,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return TenantOut(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        business_type=row["business_type"],
        plan=row["plan"],
        status=row["status"],
        settings=dict(row["settings"] or {}),
    )
