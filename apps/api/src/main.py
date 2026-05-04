"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import Settings, get_settings
from .core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    logger.info("api.startup", environment=settings.environment)

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
        title="ZapAgent API",
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

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    from .api.webhooks.whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/webhooks")

    # REST API v1 — tenant-scoped resources
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
