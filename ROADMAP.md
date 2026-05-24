# Roadmap

Tracking what's done, what's next, and what's deferred. The closer to the
top, the closer to ready.

## v0.2 -- production hardening (in flight)

- [x] WhatsApp provider abstraction (Evolution + Stub)
- [x] Request-ID middleware + readiness probe
- [x] Demo flow without external WhatsApp gateway (`make demo`)
- [x] LangGraph PostgresSaver wired to the live pool — durable
      checkpoints, per-task scope (event-loop safe under Celery prefork)
- [x] **`@lid` outbound reply path**. Python wrapper (`apps/evolution/
      lid_pipe.py`) runs as PID 1 inside the Evolution container, spawns
      Evolution as a subprocess, mirrors its stdout, and side-channels
      Baileys `(message_id, sender_pn)` pairs into Redis as
      `lid_pn:{message_id}` (24 h TTL). API webhook looks up the cache
      when the inbound JID ends in `@lid` and patches `contact_phone`
      before DB write / Celery dispatch. Cache miss falls through with a
      warning log. Works in both docker-compose AND Railway (the earlier
      Docker-SDK sidecar at `apps/api/src/sidecars/` only worked locally
      because Railway services do not share `/var/run/docker.sock` —
      removed in the refactor). Read side stays at
      `apps/api/src/integrations/whatsapp/lid.py`. (2026-05-24 late)
- [x] **Per-intent confidence rules in `check_confidence`**.
      `GREETING`, `OPT_OUT`, and slot-incomplete `SCHEDULING` now early-
      return with `confidence=1.0, next_action="respond"`;
      `INFORMATION` / `PRICING` / `OTHER` keep the FAQ-score path.
      (2026-05-24 EOD)
- [ ] Wire structured logs to OpenTelemetry (`OTEL_EXPORTER_OTLP_ENDPOINT`
      already in settings; needs OTLP exporter + spans around graph nodes)
- [x] Sentry integration (`SENTRY_DSN` already in settings) — wired in
      `apps/api/src/core/observability.py`
- [ ] **Rewrite Terraform Railway module against the real provider schema.**
      Surfaced 2026-05-24 night: the existing `infra/terraform/environments/
      railway/main.tf` was authored against an imagined API. None of the
      resources/attrs it uses (`railway_plugin`, `railway_variable_collection`,
      nested `source { }` / `build_config { }` blocks, `start_command`,
      `healthcheck_path`) exist in any published version of the
      `terraform-community-providers/railway` provider (verified against
      0.1 / 0.3.1 / 0.6.2). Deploy is dashboard-driven for now (DEPLOY.md
      §4 walks through it manually). A proper rewrite uses `source_repo`
      + `config_path` (railway.toml), per-variable `railway_variable`
      resources, and an external Redis (Upstash or a regular service
      since the plugin resource doesn't exist).
- [x] **Rate-limit circuit breaker**. Five consecutive Redis errors
      flip the breaker open for 30 s; while open, non-exempt requests
      get HTTP 503 + `Retry-After: 30` instead of fail-open. Cooldown
      transitions to half-open; a successful probe closes the circuit.
      Lives in `apps/api/src/core/rate_limit.py`; tested by
      `tests/core/test_rate_limit_breaker.py`. (2026-05-24 night)
- [ ] Backups + restore drill for Supabase (RTO < 1h, RPO < 24h target)
- [ ] Per-tenant cost dashboards (`messages.token_usage` is captured;
      need a pg view + dashboard tile)

## v0.3 -- agent quality

- [ ] Slot-filling validation against `tenants.settings.business_hours`
- [ ] Google Calendar availability check before confirming an appointment
- [ ] Handoff retry with exponential backoff + SMS/email fallback
- [ ] Embeddings cache (today: every retrieve_context call hits Voyage AI)
- [ ] Inbox view in the dashboard for pending handoffs

## v0.4 -- multi-provider

- [ ] WPP Connect adapter (`integrations/whatsapp/wppconnect.py`)
- [ ] Meta WhatsApp Cloud API adapter (`integrations/whatsapp/meta_cloud.py`)
- [ ] Per-tenant provider selection (today: process-wide via env var)

## Deferred (v0.5+)

- Voice notes / Whisper transcription
- Group-chat handling
- Custom domain per tenant for landing pages
- Phone number provisioning UX (BYO SIM vs. resell via Twilio/Z-API)
