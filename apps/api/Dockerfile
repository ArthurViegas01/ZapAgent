# Multi-stage Dockerfile for the FastAPI service.
# `dev` stage = hot-reload uvicorn used by docker-compose.
# `prod` stage = slim runtime image used by Railway.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# No apt install needed: every pip dep we use has prebuilt wheels for
# linux/amd64 (psycopg[binary], asyncpg, cryptography, Pillow, etc).
# An earlier version installed build-essential + libpq-dev defensively;
# that ~200MB layer was OOM-killed by Railway's builder
# ("runc run failed: container process is already dead" at base step 3/5
# on 2026-05-25). Stripping it both fixes the build there and shrinks the
# image. If a future dep ever needs to compile from source, add a
# `RUN apt-get update && apt-get install -y --no-install-recommends \
# build-essential libpq-dev && rm -rf /var/lib/apt/lists/*` back here.

COPY pyproject.toml ./
COPY README.md ./README.md

# ---------------------------------------------------------------------------
FROM base AS dev

RUN pip install --upgrade pip \
 && pip install -e ".[dev]"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------------------
FROM base AS prod

RUN pip install --upgrade pip \
 && pip install .

COPY . .

# Drop privileges in production.
RUN useradd --create-home --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
