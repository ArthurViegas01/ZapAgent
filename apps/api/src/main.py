"""FastAPI application factory."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .core.config import Settings, get_settings
from .core.logging import configure_logging, get_logger
from .core.observability import init_observability

logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with an ``X-Request-Id`` so we can correlate logs.

    Honors a client-supplied ``X-Request-Id`` if present (useful for tracing
    a webhook through the API and the Celery worker), otherwise generates a
    fresh UUIDv4. Also bound to structlog's contextvars so any log line
    emitted during the request automatically includes ``request_id``.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid

        # Bind to structlog's request-scoped context if available.
        try:
            import structlog  # noqa: PLC0415

            structlog.contextvars.bind_contextvars(request_id=rid)
            try:
                response = await call_next(request)
            finally:
                structlog.contextvars.unbind_contextvars("request_id")
        except Exception:
            response = await call_next(request)

        response.headers["x-request-id"] = rid
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # Sentry must initialize *before* the first request so middleware
    # captures errors from the very first webhook hit. It is idempotent
    # — multiple FastAPI apps in the test suite all share one client.
    init_observability(component="api")
    settings = get_settings()
    logger.info(
        "api.startup",
        environment=settings.environment,
        whatsapp_provider=settings.whatsapp_provider,
    )

    app.state.db_pool = None
    if settings.database_url_sync:
        try:
            from .db.pool import create_pool
            app.state.db_pool = await create_pool()
        except Exception as exc:
            logger.warning("api.db_pool.failed", error=str(exc))

    try:
        yield
    finally:
        if app.state.db_pool is not None:
            await app.state.db_pool.close()
            logger.info("api.db_pool.closed")
        logger.info("api.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Encaixe API",
        version="0.1.0",
        description="WhatsApp AI assistant — LangGraph orchestrator + REST.",
        lifespan=lifespan,
    )

    origins = ["*"] if not settings.is_production else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .core.rate_limit import RateLimitMiddleware  # noqa: PLC0415
    app.add_middleware(RateLimitMiddleware, redis_url=str(settings.redis_url))
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe -- process is up."""
        return {"status": "ok", "version": app.version}

    @app.get("/ready", tags=["meta"])
    async def ready(request: Request) -> dict[str, object]:
        """Readiness probe -- DB pool reachable, provider resolvable."""
        from .integrations.whatsapp import get_whatsapp_provider  # noqa: PLC0415

        db_ok = False
        pool = getattr(request.app.state, "db_pool", None)
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                db_ok = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("ready.db_check_failed", error=str(exc))

        provider_name = ""
        try:
            provider_name = get_whatsapp_provider().name
        except Exception as exc:  # noqa: BLE001
            logger.warning("ready.provider_failed", error=str(exc))

        ok = db_ok and bool(provider_name)
        return {
            "status": "ready" if ok else "degraded",
            "db": db_ok,
            "whatsapp_provider": provider_name,
        }

    from .api.webhooks.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/webhooks")

    # REST API v1 -- tenant-scoped resources
    from .api.v1.routers.tenants import router as tenants_router
    from .api.v1.routers.faq import router as faq_router
    from .api.v1.routers.conversations import router as conversations_router
    from .api.v1.routers.integrations import router as integrations_router
    app.include_router(tenants_router, prefix="/api")
    app.include_router(faq_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(integrations_router, prefix="/api")

    return app


app = create_app()
