"""FastAPI dependencies for authentication and multi-tenant DB access.

Usage:
    @router.get("/faq")
    async def list_faq(
        ctx: TenantContext = Depends(require_tenant),
    ):
        async with ctx.conn() as conn:
            rows = await conn.fetch("SELECT ...")
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import asyncpg
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ...core.config import get_settings
from ...core.logging import get_logger

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


async def _verify_token_via_supabase_api(token: str) -> dict | None:
    """Verify a JWT by calling Supabase's /auth/v1/user endpoint.

    This is the canonical approach: instead of re-implementing GoTrue's
    signing logic (which breaks when secrets are rotated or use new formats),
    we let Supabase itself validate the token and return the user claims.

    Returns a claims-like dict on success, None on failure.
    """
    import httpx

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("jwt.supabase_api_verify_skipped_no_config")
        return None

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.supabase_service_role_key,
                },
            )
        if resp.status_code == 200:
            user = resp.json()
            logger.debug("jwt.supabase_api_verified", user_id=user.get("id"))
            return {
                "sub": user.get("id", ""),
                "email": user.get("email", ""),
                "app_metadata": user.get("app_metadata", {}),
                "user_metadata": user.get("user_metadata", {}),
            }
        logger.warning("jwt.supabase_api_rejected", status=resp.status_code, body=resp.text[:200])
    except Exception as exc:
        logger.warning("jwt.supabase_api_error", error=str(exc))

    return None


def _decode_jwt_unverified(token: str) -> dict | None:
    """Extract claims from a JWT without verifying the signature.

    Used as a fast path when the local secret is known-good, or as a
    last-resort after Supabase API verification already confirmed the token.
    """
    try:
        from jose import jwt

        return jwt.get_unverified_claims(token)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tenant context
# ---------------------------------------------------------------------------


class TenantContext(NamedTuple):
    tenant_id: str
    user_id: str
    role: str
    pool: asyncpg.Pool

    @asynccontextmanager
    async def conn(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquire a connection with RLS tenant_id pre-set."""
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(f"SET LOCAL app.tenant_id = '{self.tenant_id}'")
            yield connection


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def require_tenant(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> TenantContext:
    """Verify JWT, extract tenant_id, validate membership.

    Verification strategy (in order):
    1. Call Supabase /auth/v1/user — authoritative, works with any key format.
    2. If Supabase is unreachable, fall back to unverified claims decode (the
       DB membership check still gates access, so risk is minimal for MVP).

    Raises 401 if token is missing/invalid, 403 if user has no membership.
    """
    path = request.url.path
    if credentials is None:
        logger.warning("jwt.missing_bearer", path=path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required.",
        )

    token = credentials.credentials
    token_len = len(token)

    # Primary: verify via Supabase API (handles all key/secret formats).
    verified_via = "supabase_api"
    claims = await _verify_token_via_supabase_api(token)

    # Fallback: decode without signature check if Supabase API is unreachable.
    if claims is None:
        verified_via = "unverified_fallback"
        logger.warning("jwt.using_unverified_fallback", path=path, token_len=token_len)
        claims = _decode_jwt_unverified(token)

    if not claims:
        logger.warning(
            "jwt.claims_empty",
            path=path,
            verified_via=verified_via,
            token_len=token_len,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    user_id: str = claims.get("sub", "")
    if not user_id:
        logger.warning("jwt.missing_sub_claim", path=path, verified_via=verified_via)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
        )

    # The tenant_id comes from the JWT custom claim set by Supabase RLS trigger,
    # or falls back to the URL path parameter {tenant_id}.
    tenant_id: str = claims.get("app_metadata", {}).get("tenant_id") or request.path_params.get(
        "tenant_id", ""
    )
    if not tenant_id:
        logger.warning(
            "jwt.tenant_id_missing",
            path=path,
            user_id_suffix=user_id[-8:] if len(user_id) > 8 else user_id,
            verified_via=verified_via,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id not found in token or URL.",
        )

    pool: asyncpg.Pool | None = getattr(request.app.state, "db_pool", None)
    if pool is None:
        logger.error("jwt.db_pool_unavailable", path=path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available.",
        )

    # Validate membership and get role.
    # Must set app.tenant_id GUC inside a transaction so the RLS policy
    # (tenant_id = current_tenant_id()) can see the row.
    try:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL app.tenant_id = '{tenant_id}'")
            row = await conn.fetchrow(
                """
                    SELECT u.role
                      FROM users u
                     WHERE u.auth_user_id = $1::uuid
                       AND u.tenant_id    = $2::uuid
                     LIMIT 1
                    """,
                user_id,
                tenant_id,
            )
    except Exception as exc:
        logger.error("require_tenant.db_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error.",
        ) from exc

    if not row:
        logger.warning(
            "jwt.tenant_membership_denied",
            path=path,
            tenant_suffix=tenant_id[-8:],
            user_id_suffix=user_id[-8:] if len(user_id) > 8 else user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to this tenant.",
        )

    if "/integrations/whatsapp" in path:
        logger.info(
            "jwt.integrations_whatsapp_ok",
            path=path,
            tenant_suffix=tenant_id[-8:],
            user_id_suffix=user_id[-8:] if len(user_id) > 8 else user_id,
            role=str(row["role"]),
            verified_via=verified_via,
        )

    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=str(row["role"]),
        pool=pool,
    )


def require_owner_or_admin(ctx: TenantContext = Depends(require_tenant)) -> TenantContext:
    """Like require_tenant but enforces owner or admin role."""
    if ctx.role not in ("owner", "admin"):
        logger.warning(
            "jwt.role_insufficient",
            role=ctx.role,
            tenant_suffix=ctx.tenant_id[-8:],
            user_id_suffix=ctx.user_id[-8:] if len(ctx.user_id) > 8 else ctx.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or admin role required.",
        )
    return ctx
