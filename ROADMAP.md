# Roadmap

Tracking what's done, what's next, and what's deferred. The closer to the
top, the closer to ready.

## v0.2 -- production hardening (in flight)

- [x] WhatsApp provider abstraction (Evolution + Stub)
- [x] Request-ID middleware + readiness probe
- [x] Demo flow without external WhatsApp gateway (`make demo`)
- [x] LangGraph PostgresSaver wired to the live pool — durable
      checkpoints, per-task scope (event-loop safe under Celery prefork)
- [x] **`@lid` outbound reply path**. Sidecar tails Evolution stdout
      via the Docker socket, parses Baileys `recv` lines for
      `(message_id, sender_pn)`, caches at `lid_pn:{message_id}` in
      Redis with a 24 h TTL. Webhook handler looks up the cache when
      the inbound JID ends in `@lid` and patches `contact_phone` before
      DB write / Celery dispatch. Cache miss falls through with a
      warning log so the inbound is still persisted. Lives at
      `apps/api/src/sidecars/lid_resolver.py` +
      `apps/api/src/integrations/whatsapp/lid.py`. Docker-compose
      service `lid-resolver`. (2026-05-24 EOD)
- [x] **Per-intent confidence rules in `check_confidence`**.
      `GREETING`, `OPT_OUT`, and slot-incomplete `SCHEDULING` now early-
      return with `confidence=1.0, next_action="respond"`;
      `INFORMATION` / `PRICING` / `OTHER` keep the FAQ-score path.
      (2026-05-24 EOD)
- [ ] Wire structured logs to OpenTelemetry (`OTEL_EXPORTER_OTLP_ENDPOINT`
      already in settings; needs OTLP exporter + spans around graph nodes)
- [x] Sentry integration (`SENTRY_DSN` already in settings) — wired in
      `apps/api/src/core/observability.py`
- [ ] Rate-limit circuit breaker (today: fail-open if Redis unreachable;
      switch to fail-closed after N consecutive Redis errors)
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
