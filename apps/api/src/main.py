"""FastAPI application factory.

The factory pattern keeps tests honest: each test that needs a fresh app
constructs it with overridden dependencies via `app.dependency_overrides`.
"""

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
    """Startup/shutdown hooks. DB pool init goes here when wired up."""
    configure_logging()
    logger.info("api.startup", environment=get_settings().environment)
    try:
        yield
    finally:
        logger.info("api.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="ZapAgent API",
        version="0.1.0",
        description="WhatsApp AI assistant — LangGraph orchestrator + REST.",
        lifespan=lifespan,
    )

    # CORS: in production this list is tightened to the dashboard domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    # Routers — wired up as we build them.
    # from .api.webhooks.whatsapp import router as whatsapp_router
    # app.include_router(whatsapp_router, prefix="/webhooks")

    return app


app = create_app()
