# Changelog

All notable changes to ZapAgent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **WhatsApp provider abstraction** (`apps/api/src/integrations/whatsapp/`).
  The pipeline now talks to a `WhatsAppProvider` interface; concrete
  implementations live alongside it (`evolution.py`, `stub.py`).
- **StubProvider** for E2E tests, demos, and local-only dev. Switch via
  `WHATSAPP_PROVIDER=stub` -- no Evolution API key required.
- `make demo` -- runs a full conversation through StubProvider against the
  LangGraph agent with no external network.
- `make seed` and `db/migrations/seed_demo.sql` -- a demo tenant + FAQ rows.
- `make up-stub` -- brings up the local stack without the evolution container.
- `/ready` endpoint -- liveness/readiness with DB ping and provider check.
- Request-ID middleware -- every request gets `X-Request-Id`, bound to
  structlog contextvars and echoed in the response. Honors a client-supplied
  ID so a webhook can be traced through the API and Celery worker.
- `EVOLUTION_WEBHOOK_BASE_URL` setting (replaces ad-hoc `os.environ.get`).
- New tests: `tests/integrations/test_whatsapp_provider.py` (12 tests).
- `test_scheduling_without_appointment_falls_through_to_respond` test
  documents the new contract: scheduling intent without an extracted slot
  routes to `respond` (LLM asks for the slot), never silently books a
  placeholder.

### Changed
- `webhooks/whatsapp.py` is now provider-agnostic. The Evolution-specific
  payload knowledge moved into `EvolutionProvider`.
- `worker/tasks.py` `_send_whatsapp_reply` delegates to the active provider
  instead of calling Evolution's `httpx` directly.
- `routers/integrations.py` `connect_whatsapp` / `disconnect_whatsapp` /
  `whatsapp_status` route through the provider; Evolution-specific QR
  polling stays guarded behind `isinstance(provider, EvolutionProvider)`.
- Webhook auth migrated from the global `apikey` header to a per-instance
  `token` header (least-privilege; we set `EVOLUTION_WEBHOOK_TOKEN` when
  creating the instance and verify it on every event).

### Fixed
- `check_confidence` no longer routes to `schedule` when the agent has
  no extracted appointment slot. Without this guard, a scheduling intent
  without slots silently booked a "tomorrow + 30min" placeholder.
- Removed unused `pool=None` parameter from `_send_whatsapp_reply`.
- Removed inline `os.environ.get("EVOLUTION_WEBHOOK_BASE_URL", ...)` in
  favor of typed settings.
- `docker-compose.yml` header comment now describes the actual stack
  (was incorrectly mentioning `wppconnect-server`).

## [0.1.0] - 2026-04-28

Initial scaffold (96 files): FastAPI + LangGraph agent (6 nodes), Next.js
14 dashboard, Supabase Postgres + pgvector, RLS migrations, Evolution API
WhatsApp gateway, Celery worker, Terraform for Hetzner + AWS + Railway,
GitHub Actions for CI/CD, docker-compose for local dev. Evolution-coupled
flow: `messages.upsert` / `qrcode.updated` / `connection.update` events.
