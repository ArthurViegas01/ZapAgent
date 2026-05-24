"""Centralized observability bootstrap.

Today this is Sentry-only. OpenTelemetry is on the ROADMAP for v0.2 and
will be wired in this module so the rest of the codebase keeps depending
on a single ``init_observability()`` call.

Design choices
--------------
* **Single entrypoint** — both the FastAPI app (``main.py``) and the
  Celery worker (``worker/celery_app.py``) call ``init_observability()``.
  The function is idempotent: re-invoking it (which happens in tests
  that build multiple FastAPI apps) just returns without re-init.
* **No DSN ⇒ no-op** — local development without a Sentry project should
  not log "init failed" noise. Missing DSN is silently treated as "off".
* **PII off by default** — agent logs contain `contact_phone`,
  `user_message`, etc. We rely on application-level structlog for
  business observability and use Sentry strictly for exceptions and
  performance. ``send_default_pii=False`` keeps Sentry from grabbing
  request bodies / headers / cookies.
* **Integrations explicit** — FastAPI, Starlette, Celery, httpx, asyncpg
  cover the entire request path. Logging integration is **disabled** so
  structlog stays the single source of truth for application logs (we
  don't want every WARNING line to also become a Sentry event).
"""

from __future__ import annotations

from typing import Any

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)

_INITIALIZED = False


def _build_integrations() -> list[Any]:
    """Lazy-import sentry integrations so importing this module is free
    when sentry-sdk is absent (it shouldn't be, but pyproject extras can
    drift in monorepos)."""
    from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    return [
        FastApiIntegration(transaction_style="endpoint"),
        StarletteIntegration(transaction_style="endpoint"),
        CeleryIntegration(monitor_beat_tasks=True),
        HttpxIntegration(),
        AsyncPGIntegration(),
        # Logging stays via structlog; sending every WARNING to Sentry
        # would drown signal in noise. We only want exceptions.
        LoggingIntegration(level=None, event_level=None),
    ]


def init_observability(component: str) -> None:
    """Initialize observability for a process.

    Args:
        component: short tag attached to every event so the Sentry UI can
            tell "api" events from "worker" events on the same DSN.
            Use ``"api"`` or ``"worker"``.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    settings = get_settings()
    if not settings.sentry_dsn or not settings.sentry_dsn.strip():
        logger.info("observability.sentry_skipped", reason="no_dsn")
        _INITIALIZED = True
        return

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("observability.sentry_skipped", reason="sentry_sdk_not_installed")
        _INITIALIZED = True
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        attach_stacktrace=True,
        integrations=_build_integrations(),
    )
    sentry_sdk.set_tag("component", component)

    logger.info(
        "observability.sentry_initialized",
        component=component,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        release=settings.sentry_release or "unset",
    )
    _INITIALIZED = True


def reset_for_tests() -> None:
    """Allow tests to force a re-init (rarely needed)."""
    global _INITIALIZED
    _INITIALIZED = False
