"""Celery application factory.

Usage (local dev via docker compose):
    celery -A src.worker.celery_app worker --loglevel=INFO --concurrency=2

Beat scheduler (LGPD retention job):
    celery -A src.worker.celery_app beat --loglevel=INFO
"""

from __future__ import annotations

from celery import Celery

from src.core.config import get_settings
from src.core.observability import init_observability

# Wire Sentry before constructing the Celery app so the CeleryIntegration
# can hook into the lifecycle of every task. ``init_observability`` is a
# no-op when SENTRY_DSN is unset, so local dev / tests stay quiet.
init_observability(component="worker")

settings = get_settings()

app = Celery(
    "zapagent",
    broker=str(settings.celery_broker_url),
    backend=str(settings.celery_result_backend),
    include=["src.worker.tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "lgpd-retention-nightly": {
            "task": "tasks.purge_old_messages",
            "schedule": 86400,
            "options": {"expires": 3600},
        },
    },
)
