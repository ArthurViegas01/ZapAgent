# Roadmap

Tracking what's done, what's next, and what's deferred. The closer to the
top, the closer to ready.

## v0.2 -- production hardening (in flight)

- [x] WhatsApp provider abstraction (Evolution + Stub)
- [x] Request-ID middleware + readiness probe
- [x] Demo flow without external WhatsApp gateway (`make demo`)
- [x] LangGraph PostgresSaver wired to the live pool — durable
      checkpoints, per-task scope (event-loop safe under Celery prefork)
- [ ] **`@lid` outbound reply path** (PRODUCTION BLOCKER). Modern
      Brazilian WhatsApp accounts use the `@lid` privacy JID instead
      of `@s.whatsapp.net`; Evolution 2.2.3 doesn't expose the
      `sender_pn` mapping in its webhook, so `sendText` for those
      contacts returns 400. Path forward: sidecar that tails
      Evolution stdout, parses `sender_pn` per `message_id`, and caches
      to Redis; webhook handler enriches `contact_phone` via lookup.
      Surfaced during the 2026-05-24 manual end-to-end test (both
      contacts the user tried — different numbers, different SIMs —
      were `@lid`-mode).
- [ ] **Per-intent confidence rules in `check_confidence`**. Today the
      node computes confidence from the top FAQ-match score regardless
      of intent, so a casual `GREETING` ("Oi") cosine-misses every FAQ
      and lands at confidence ~0.18 → handoff. Fix: `GREETING` /
      `OPT_OUT` / slot-incomplete `SCHEDULING` should set confidence
      from intent classification, not retrieval. Same test session
      surfaced this.
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
