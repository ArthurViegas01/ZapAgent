"""Celery application factory.

Keeps broker/backend configuration in one place. Tasks are discovered
automatically from src.worker.tasks when the worker process starts.

Usage (local dev via docker compose):
    celery -A src.worker.celery_app worker --loglevel=INFO --concurrency=2
"""

from __future__ import annotations

from celery import Celery

from src.core.config import get_settings

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
    # Prevent tasks from being acked before they finish (safer default).
    task_acks_late=True,
    # Do not pre-fetch more than one task per worker process.
    worker_prefetch_multiplier=1,
)
