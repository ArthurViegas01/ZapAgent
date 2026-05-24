# Encaixe — Architecture

> WhatsApp AI assistant SaaS for Brazilian small businesses (barbershops,
> clinics, pet shops, garages). This document captures the validated
> architecture, the rationale for each choice, and the deviations from the
> initial proposal with their justification.

## 1. High-level topology

```
+---------------------+         +-----------------------------+
|  Next.js Dashboard  |  HTTPS  |        FastAPI API          |
|  (Vercel)           +-------->+  (VPS, co-located)          |
|  Multi-tenant UI    |  JWT    |  - REST: tenants, FAQ, etc. |
+----------+----------+         |  - Webhook receivers        |
           |                    |  - LangGraph orchestrator   |
           |                    +------+------+---------------+
           |                           |      |
           | Supabase Auth             |      | Celery jobs
           v                           v      v
+---------------------+         +------+------+--------+
|  Supabase           |         |  Redis (broker)      |
|  - Postgres + RLS   |         +------+---------------+
|  - pgvector         |                |
|  - Auth, Storage    |                v
+----------+----------+         +------+---------------+
           ^                    |  Celery Worker(s)    |
           |                    |  - LLM calls         |
           |                    |  - Calendar API      |
           |                    +------+---------------+
           |                           |
+----------+----------+                |
|  Evolution API      +<---------------+
|  (same VPS as API)  |  WhatsApp Business
+---------------------+
```

## 2. Deviations from the initial proposal

### 2.1. Co-locate FastAPI and Evolution API on the same VPS

**Original plan:** FastAPI on Railway/Render + Evolution API on Hetzner VPS.

**Problem:** every inbound WhatsApp message triggers an Evolution → FastAPI
webhook, and every outbound reply triggers a FastAPI → Evolution HTTP call.
Splitting them across providers adds 50–200 ms of cross-network latency per
hop, plus egress cost on Railway and a second set of secrets to keep in sync.

**Decision:** run both on the same Hetzner VPS via Docker Compose / a small
Nomad or Docker stack. Vercel keeps the Next.js dashboard. Supabase keeps the
database. This reduces the production surface to three managed pieces (Vercel,
Supabase, one VPS) and keeps WhatsApp-path latency local.

### 2.2. Async processing for LLM-bound work

**Problem:** LangGraph runs (intent → retrieve → generate → confidence) take
3–15 s end-to-end. Evolution API webhooks must be acknowledged in < 5 s or
they retry. Holding the HTTP connection while the LLM streams will cause
duplicate messages and stuck workers.

**Decision:** the webhook handler does only persistence (insert message,
deduplicate by `message_id`) and returns 200 immediately. A Celery task picks
up the message, runs the LangGraph turn, and posts the reply via Evolution.
Redis is the broker (it is already in the stack for Evolution caching).

### 2.3. Idempotent webhook ingestion

Evolution API retries on non-2xx responses and on timeouts. Without a dedupe
layer the agent will reply to the same message multiple times.

**Decision:** every webhook payload carries a provider message id; we persist
it in `webhook_events` with a unique constraint and return 200 on conflict
without enqueuing a second task.

### 2.4. Multi-tenant isolation: defense in depth

Three layers, all enforced:

1. **Database — Supabase RLS** on every tenant-scoped table. Policies use
   `auth.jwt() ->> 'tenant_id'` for the dashboard role.
2. **Application — tenant context** set per request via FastAPI dependency.
   Every query goes through a session that calls
   `SET LOCAL app.tenant_id = '<uuid>'`; a Postgres policy checks it for the
   service role too. This prevents accidental cross-tenant reads when the
   service role key is used.
3. **Webhook routing** — Evolution instance name → tenant id mapping is the
   only way an inbound message gets attributed; the mapping lives in the
   `integrations` table.

### 2.5. LangGraph state persistence

Use `langgraph.checkpoint.postgres.PostgresSaver` against the same Postgres
instance. Thread id = `(tenant_id, conversation_id)`. This gives us:
durable state across restarts, time-travel for debugging, and the ability to
resume after a `handoff_human` interrupt when the operator replies.

### 2.6. Google Calendar OAuth per tenant

Stored as `integrations.config` (refresh token encrypted at rest). A
background sweep refreshes tokens before expiry. The OAuth callback URL is
`https://app.zapagent.com.br/integrations/google/callback`; the dashboard
holds the consent flow because the API doesn't render HTML.

### 2.7. Cost & unit-economics tracking from day 1

R$297/mês ≈ ~US$60. Claude Haiku at typical Brazilian SMB volume (200–800
turns/month) is well within budget, but we instrument it anyway. Every LLM
call is logged in `messages.token_usage` (input/output/cached) so per-tenant
margin is queryable.

### 2.8. LGPD compliance hooks

- `tenants.data_retention_days` defaults to 365.
- A nightly job purges `messages` older than that, keeping `conversations`
  metadata for analytics.
- Opt-out keywords ("PARAR", "SAIR") set `conversations.opted_out = true` and
  the agent stops replying for that contact.
- Audit log in `webhook_events` for each inbound/outbound message.

### 2.9. WhatsApp provider abstraction (port + adapters)

The agent pipeline never imports a vendor-specific WhatsApp client. It
depends on the `WhatsAppProvider` interface in
`apps/api/src/integrations/whatsapp/base.py`. Concrete adapters live in
the same package:

| Adapter          | When to use                                     |
|------------------|-------------------------------------------------|
| `EvolutionProvider` | Production with self-hosted Evolution API    |
| `StubProvider`      | Local dev / E2E tests / demos (no network)   |

**Why a port + adapters and not a feature flag inside the route handlers**

1. **Testability.** With Stub we run the full pipeline -- webhook ingest,
   dedup, agent graph, outbound send -- without any external dependency.
2. **Vendor risk.** Evolution API depends on Baileys, which depends on
   WhatsApp's reverse-engineered protocol. If an account gets banned,
   if Evolution has an outage, or if we want to migrate to the official
   Meta WhatsApp Cloud API, the swap is one new file + one env-var flip.
3. **Webhook auth model.** We migrated from the Evolution global `apikey`
   header (admin-level) to a per-instance `token` header (least
   privilege) by adding `verify_webhook_auth` to the interface and
   keeping the choice provider-local.

Switch via `WHATSAPP_PROVIDER` (settings.py validates the literal):

```bash
WHATSAPP_PROVIDER=evolution  # default
WHATSAPP_PROVIDER=stub       # for `make demo` and CI
```

A new provider plugs in by:

1. Subclassing `WhatsAppProvider`, implementing every abstract method.
2. Registering it in `factory.py`.
3. Adding the literal to `settings.whatsapp_provider`.

No router or worker code changes.

## 3. Components

| Component       | Tech                                    | Where        |
|-----------------|-----------------------------------------|--------------|
| Dashboard       | Next.js 14 App Router, TS, Tailwind     | Vercel       |
| API             | FastAPI + Pydantic v2                   | Hetzner VPS  |
| Worker          | Celery (Redis broker)                   | Hetzner VPS  |
| Agent           | LangGraph + PostgresSaver               | inside API   |
| LLM             | Claude Haiku via Anthropic API          | external     |
| WhatsApp port   | `WhatsAppProvider` interface + factory  | inside API   |
| WhatsApp impl   | Evolution API (prod) / Stub (dev/tests) | Hetzner VPS  |
| Database        | Supabase Postgres + pgvector            | Supabase     |
| Auth/Storage    | Supabase                                | Supabase     |
| Payments        | Asaas                                   | external     |
| Secrets         | AWS Secrets Manager (prod) / .env (dev) | AWS          |
| IaC             | Terraform (Hetzner + AWS providers)     | repo         |
| CI/CD           | GitHub Actions                          | GitHub       |

## 4. LangGraph state machine

```
            START
              v
       classify_intent
              v
       retrieve_context
              v
       generate_response
              v
       check_confidence
        /     |      \
   low /  med |  appointment
      v      v       v
 handoff   END   schedule_appointment
                       v
                      END
```

Each node is a pure function `state -> partial state`. Conditional edges
inspect `state["intent"]` and `state["confidence"]`. Tests exercise nodes
in isolation by feeding a hand-built state and asserting on the diff.

## 5. Open questions deferred to v0.2

- Phone number provisioning UX (does each tenant bring their own SIM, or do
  we resell numbers via a partner like Twilio/Z-API?).
- Group-chat handling (off for MVP — agent only responds to 1:1 chats).
- Voice notes (off for MVP — Whisper integration is a v0.2 task).
- Custom domain per tenant for the customer-facing landing page.
