# Changelog

All notable changes to ZapAgent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (production-blocker close-out, 2026-05-24 EOD)
The two known issues recorded after the morning e2e test are closed.
Counts after this batch: **102/102 unit, 4/5 integration** (the 5th
integration test, `test_rls_guc_isolates_faq_items`, requires
``SET ROLE``, which the Supabase pooler intentionally blocks — same
behavior as before this session).

- **`@lid` contact resolver sidecar** — closes the WhatsApp privacy-mode
  outbound-reply blocker. Evolution 2.2.3 drops Baileys' ``sender_pn``
  before emitting webhook payloads, so privacy-mode contacts arrive with
  a masked ``<digits>:<device>@lid`` JID and ``sendText`` 400s on the
  way back out. New pieces:
  * `apps/api/src/sidecars/lid_resolver.py` — daemon that streams
    ``encaixe-evolution``'s stdout through the Docker socket, parses
    ``recv`` lines for ``(message_id, sender_pn)``, and caches the
    mapping at ``lid_pn:{message_id}`` in Redis with a 24 h TTL.
    `parse_recv_line` is a pure function (13 unit tests).
  * `apps/api/src/integrations/whatsapp/lid.py` — async read-side
    helper; webhook calls this when the inbound JID ends in ``@lid``.
    Singleton aioredis client with `socket_connect_timeout=1` so a
    dead resolver can't stall the webhook.
  * `apps/api/src/api/webhooks/whatsapp.py` — patches
    ``inbound.contact_phone`` via `dataclasses.replace` when the
    sidecar resolves the JID; falls through with the masked phone +
    warning log when the cache misses (so the inbound is still
    persisted and gaps show up in observability).
  * `docker-compose.yml` — new `lid-resolver` service. Read-only bind
    of `/var/run/docker.sock`. Reuses the API image so we don't fork
    a separate build pipeline; the `docker` Python SDK is the only
    new runtime dep (~200 KB) and ships in the same wheel layer.
  * `apps/api/pyproject.toml` — added `docker>=7.1.0`.
  Not done in this batch: upstream PR to evolution-api to expose
  ``senderPn`` in the webhook payload natively. The sidecar is the
  unblock; the upstream patch is the cleanup.

- **Per-intent confidence rules in `check_confidence`** — closes the
  UX bug where a casual ``GREETING`` cosine-missed every FAQ row and
  routed to handoff. `apps/api/src/agent/nodes/check_confidence.py`
  now early-returns ``confidence=1.0, next_action=respond`` for
  ``GREETING``, ``OPT_OUT``, and slot-incomplete ``SCHEDULING``;
  ``INFORMATION`` / ``PRICING`` / ``OTHER`` and ``SCHEDULING`` with an
  appointment draft still use the FAQ-score path against
  ``agent_confidence_threshold``. Three new tests in
  `apps/api/tests/agent/test_check_confidence.py` cover greeting,
  scheduling-without-appointment-low-score (the original bug), and
  pricing-low-score-still-handoffs (the *anti*-regression: we must
  not short-circuit real information seeking).

### Added (tests)
- `apps/api/tests/integration/test_per_task_pool_scoping.py` —
  regression for the 4d6d9be event-loop fix. Two consecutive
  ``asyncio.run`` invocations of the worker-pool scope and the
  PostgresSaver scope must both succeed. Reproduces the Celery prefork
  lifecycle; would crash with "bound to a different event loop" if any
  future refactor reintroduces a process-singleton pool/lock/saver.
  Gated by the existing ``integration_dsn`` fixture so it skips
  cleanly when Postgres is unreachable.

### Fixed (end-to-end WhatsApp pairing test, 2026-05-24 PM)
Bugs caught during the first real WhatsApp pair-and-message test against
Supabase production (project `oodfxbrbawcnromvhjga`). Inbound flow
(webhook → Celery → LangGraph → response generated → persisted) now
works end-to-end; outbound delivery for `@lid` contacts is a separate
production blocker tracked under "Known issues" below.

- `apps/api/src/db/pool.py` — replaced the process-singleton
  `_worker_pool` global with `worker_pool_scope()`, an async context
  manager that opens a fresh `asyncpg` pool per Celery task and closes
  it on exit. Celery prefork workers run each task inside its own
  `asyncio.run()` loop; the previous pool was bound to whatever loop
  ran the first task in the worker process, and every subsequent task
  crashed with `RuntimeError: ... Event loop is closed` when calling
  `pool.acquire()`. Per-task scoping costs ~50 ms TCP connect per task
  (negligible vs the multi-second LLM call) and eliminates the hazard.
- `apps/api/src/agent/checkpointer.py` — same fix for the psycopg pool
  feeding `AsyncPostgresSaver`. Replaced the module-level `_pool`,
  `_saver`, and `_init_lock = asyncio.Lock()` globals with
  `async_postgres_saver_scope()`, a context manager that opens the
  pool, runs `setup()` once per DSN per process, yields the saver, and
  closes the pool. The previous code crashed mid-graph at
  `aput_writes` with `<asyncio.locks.Lock object> is bound to a
  different event loop` for the same reason — the lock was created at
  module import time (no loop bound) but `.acquire()`'d in task A's
  loop, then re-used after task A's loop closed.
- `apps/api/src/worker/tasks.py` — `_main` and `_run_agent` now wrap
  their work in the new context managers (`worker_pool_scope` +
  `async_postgres_saver_scope`). `_run_agent` keeps the
  fallback-to-`MemorySaver` branch via try/except around the
  scope. `purge_old_messages` migrated to the same pattern.
- `apps/api/src/agent/context.py` — **new module** exposing
  `set_db_pool` / `get_db_pool` on a `contextvars.ContextVar`. The
  worker calls `set_db_pool(pool)` before `graph.ainvoke`; the
  `retrieve_context` node reads it back. Why a contextvar instead of
  the LangGraph `config["configurable"]` dict: LangGraph (current
  pinned version) drops our `db_pool` key from `configurable` before
  the node is invoked — observed empirically with
  `configurable_keys=[]` in the no-pool log path. The framework also
  emits a warning that the `RunnableConfig | None` annotation isn't
  recognized; contextvars sidestep both issues entirely. The node
  still falls back to the LangGraph config for forward-compat.
- `apps/api/src/agent/nodes/retrieve_context.py` +
  `apps/api/src/api/v1/routers/faq.py` — the Voyage embed call now
  passes `output_dimension=1024` explicitly. `voyage-3-lite` defaults
  to 512 dims and crashes on insert into `faq_items.embedding`
  declared as `VECTOR(1024)`. The default model in `.env.example`
  also moved to `voyage-3` (which accepts 1024 natively); `voyage-3-lite`
  refuses anything but 512 dims, so the schema dim was the source of
  truth.
- `.gitignore` — added `.env.bak*` to cover the per-session backups
  generated when switching between local-postgres and Supabase pooler
  configs.

#### Known issues surfaced by this test (tracked in ROADMAP)

- **WhatsApp `@lid` contacts cannot receive replies.** Evolution 2.2.3
  passes the `key.remoteJid` through to the webhook unchanged
  (`<digits>@lid`). Bare digits parsed off that JID are not a valid
  phone number — `sendText` returns `400 Bad Request {"exists":false}`.
  The real `@s.whatsapp.net` is exposed by Baileys as `sender_pn` in
  its raw socket log but Evolution drops the field before emitting the
  webhook (grep returns zero matches in `dist/main.js`). Modern
  Brazilian WhatsApp accounts default to `@lid` privacy, so this is
  a production blocker for the SaaS gate; a sidecar that tails
  Evolution stdout and caches `(message_id → sender_pn)` is the
  current path forward.
- **`check_confidence` derives confidence from FAQ match score even for
  intents where FAQ retrieval isn't the signal.** A `GREETING` like
  "Oi" produces no semantic match against FAQ rows, so confidence is
  ~0.18 and `next_action=handoff` — the user receives the "vou chamar
  um atendente humano" reply for a casual greeting. Same for
  `SCHEDULING` when the offline-fallback path returns a clarifying
  question. The fix is per-intent confidence rules; tracked.

### Fixed (local-test pass, 2026-05-24)
Bugs caught when running the full TESTING.md playbook end-to-end. All
test suites passing after these: 83/83 unit, 3/3 integration, 4/4 demo
conversations, smoke API checks.

- `db/migrations/0001_init.sql` — added missing `CREATE UNIQUE INDEX
  idx_faq_tenant_question ON faq_items(tenant_id, question)`. The
  `seed_demo.sql` script already used `ON CONFLICT (tenant_id, question)`
  without the constraint existing, so re-running the seed silently
  inserted duplicates.
- `db/migrations/0002_fix_rls_for_js_client.sql` — created an `auth.uid()`
  stub (returns NULL) under a fresh `auth` schema. Supabase provides
  this natively in production; local Postgres does not, and migration
  0002 references it in the new policies, breaking `make migrate` on a
  clean DB. The stub returning NULL is correct semantically: locally
  there is no Supabase JWT, so the policy path that uses `auth.uid()`
  must short-circuit to "no match" instead of throwing.
  **Follow-up applied immediately:** the original fix used
  `CREATE OR REPLACE FUNCTION`, which in Supabase would overwrite their
  real `auth.uid()` with the NULL stub and silently break all JS-client
  RLS reads in production. Wrapped in a `DO`/`pg_proc` existence check
  so the CREATE only runs when the function is absent — no-op under
  Supabase, creates the stub locally.
- `apps/api/src/core/observability.py` — added `.strip()` to the DSN
  guard. pydantic-settings preserves inline comments after `VAR=` in
  `.env` files (the value becomes `" # optional"` literally), which
  crashed `sentry_sdk.init` on boot. Also normalized the `.env.example`
  to put comments on their own line.
- `Makefile` — `up-stub` no longer uses the Unix-only inline-env syntax
  (`VAR=value make ...`); under Windows Make that pattern is silently
  swallowed. `WHATSAPP_PROVIDER` is now expected to live in `.env` (per
  TESTING.md A.1) and the target just runs `docker compose up`.
- `apps/api/tests/integration/test_rls_isolation.py` (+ conftest) —
  replaced `SET LOCAL app.tenant_id = $1` with
  `SELECT set_config('app.tenant_id', $1, true)`. Postgres rejects bind
  parameters in `SET LOCAL` syntactically; `set_config(name, value,
  is_local=true)` is the documented equivalent that accepts parameters.
- `apps/api/pyproject.toml` — added
  `asyncio_default_fixture_loop_scope = "session"` so the
  session-scoped DB pool fixture stops fighting pytest-asyncio's default
  function-scoped loop. The integration suite required this to stop
  recreating the pool per test.
- `apps/api/tests/test_webhook_whatsapp.py` — adjusted the asyncpg
  fetchrow mock ordering. The billing-gate check I added in P0 #5
  consumes one fetchrow before the webhook handler's existing reads,
  shifting every downstream mock by one slot.

### Added
- **Local testing runbook** (`TESTING.md`, `make smoke-local`).
  Reproducible playbook for validating the full stack on a developer
  laptop before deploying. Two paths — (A) StubProvider, exercises
  LangGraph + webhook + Celery + billing gate offline; (B) Evolution
  real, full WhatsApp pairing + message round-trip. Each path lists
  explicitly what it does NOT cover so the operator knows when to
  switch. Includes a triage table for the common local failures.
  `make smoke-local` reuses `scripts/smoke_test_prod.py` against
  `localhost:8000` / `:3000` — same script that gates production.
- **Deploy runbook + smoke test** (`DEPLOY.md`, `scripts/smoke_test_prod.py`).
  `DEPLOY.md` reorganized as a 10-step checklist runbook (prereqs, secrets,
  Supabase migrations, Terraform Railway, Netlify, GitHub secrets, smoke
  test, pilot tenant + WhatsApp connection, billing, rollback). Companion
  Python smoke test (stdlib-only, no repo deps) probes `/health`, `/ready`,
  the dashboard root + login route, and optionally the billing endpoint
  with a real JWT — for use right after `terraform apply` succeeds.

### Fixed
- **Terraform Railway env: 4 production-blocking gaps closed**
  (`infra/terraform/environments/railway/{main,variables,terraform.tfvars.example}.tf`,
  `.github/workflows/terraform.yml`, `.github/workflows/web.yml`):
  1. Evolution service now builds from `apps/evolution/Dockerfile` instead
     of `atendai/evolution-api:latest`, preserving the Baileys 6.7.9 pin
     that fixes the noise-protocol handshake (without this, QR never
     generates in production — same bug already proven locally).
  2. `EVOLUTION_WEBHOOK_BASE_URL` now defaults to the API service's public
     URL on Railway; the settings default of `http://api:8000/...` is a
     docker-compose-only DNS name that never resolved in prod, so inbound
     webhooks were silently dropped.
  3. `EVOLUTION_WEBHOOK_TOKEN` is now an explicit Terraform variable
     instead of relying on the `"changeme"` default (which "worked" by
     accident as long as both sides agreed on the placeholder).
  4. `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, and `SENTRY_RELEASE`
     (the last derived from Railway's built-in `$RAILWAY_GIT_COMMIT_SHA`)
     are now propagated to both api and worker services, so the wiring
     added earlier actually fires in production. `web.yml` also threads
     `NEXT_PUBLIC_SENTRY_DSN` through the Netlify build for the upcoming
     `@sentry/nextjs` follow-up.
- **Subscription gate (trial + suspension), no Asaas dependency**
  (`apps/api/src/core/billing_gate.py`,
  `db/migrations/0003_billing_trial.sql`).
  New columns `tenants.subscription_status` (`trialing | active | past_due
  | suspended`, default `trialing`) and `tenants.trial_ends_at`, plus a
  partial index. Backfill grants existing tenants a 14-day trial.
  The webhook handler in `api/webhooks/whatsapp.py` now calls
  `check_subscription(pool, tenant_id)` before enqueuing Celery work; if
  the gate denies, we reply to the customer in pt-BR (`trial_expired` /
  `suspended` / `tenant_not_found`) via the active WhatsApp provider and
  skip the agent run — no LLM tokens burned for a non-paying customer.
  `past_due` is grace-period (still allowed); operations alert through
  the dashboard, not by silently dropping the customer.
  New `GET /v1/tenants/{tenant_id}/billing` endpoint exposes the same
  decision to the dashboard so banner copy and runtime gate cannot drift.
  Overview page shows a `BillingBanner` for every non-`active` state
  (trial countdown, past-due warning, suspended pause). Unit tests in
  `tests/test_billing_gate.py` cover the full status matrix.
  Migration 0003 applied in `make migrate`, `make test-integration`, and
  CI; `seed_demo.sql` updated to set `subscription_status='active'` so
  `make demo` is never blocked.
- **LangGraph PostgresSaver durable checkpoints** (`apps/api/src/agent/checkpointer.py`).
  Fulfills the promise in ARCHITECTURE.md §2.5: conversation state now
  survives worker restarts via `AsyncPostgresSaver` instead of evaporating
  with `MemorySaver`. Process-level psycopg `AsyncConnectionPool` (size 1-4)
  amortizes connection cost across Celery tasks; `setup()` runs exactly once
  per process under an `asyncio.Lock`. `worker.tasks._run_agent` now wires
  the saver into `build_graph(checkpointer=...)`, with a logged fallback to
  `MemorySaver` if init fails (turn still completes; failure is surfaced via
  Sentry rather than blocking the customer).
  New unit tests in `tests/agent/test_checkpointer_wiring.py` cover the
  custom-checkpointer pass-through and the fallback branch without needing
  a real Postgres.
  New deps: `psycopg-pool>=3.2.0`.
- **Sentry wiring for API + Worker** (`apps/api/src/core/observability.py`).
  Single `init_observability(component=...)` entrypoint, idempotent, no-op
  when `SENTRY_DSN` is empty. Wired with FastAPI/Starlette, Celery (with
  beat task monitoring), httpx and asyncpg integrations. Logging
  integration is disabled on purpose so structlog stays the single source
  of truth for application logs — only exceptions reach Sentry.
  `send_default_pii=False` keeps WhatsApp message bodies out of issues.
  New settings: `SENTRY_TRACES_SAMPLE_RATE` (default 0.1) and
  `SENTRY_RELEASE` (set by CI from `$GITHUB_SHA`).
  Follow-up: Next.js Sentry init (`@sentry/nextjs`) — needs a `pnpm add`
  pass; tracked separately.
- **Tenant-isolation integration tests** (`apps/api/tests/integration/`).
  Three real-database tests that prove the three doors through which a
  multi-tenant data leak could happen are sealed:
  1. RLS via the `app.tenant_id` GUC actually filters rows when the
     connection role is `NOBYPASSRLS` (a dedicated `app_user_test` role
     is created idempotently inside the fixture).
  2. `retrieve_context._query_faq` returns only the requesting tenant's
     FAQ rows, even with a vector that would match every seeded row.
  3. `webhooks.whatsapp._resolve_tenant` maps instance_name → tenant_id
     correctly and returns `None` for unknown instances.
  Gated behind the `integration` pytest marker (`pytest -m integration`)
  and skipped automatically if Postgres is unreachable, so they don't
  break devs without `docker compose up`.
- `make test-integration` Makefile target that applies both migrations
  idempotently and runs the integration suite inside the API container.
- CI `api.yml` now (a) applies migration `0002_fix_rls_for_js_client.sql`
  in addition to `0001_init.sql` (it was being skipped, so CI was
  drifting from production), and (b) runs the integration suite in a
  dedicated step after the unit run.
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
