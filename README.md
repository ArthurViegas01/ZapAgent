# Encaixe

WhatsApp AI assistant SaaS for Brazilian small businesses. The agent answers
FAQs, schedules appointments on Google Calendar, and hands off to a human
when confidence is low.

## Stack

- **Dashboard**: Next.js 14 (App Router) + TypeScript + Tailwind, on Vercel
- **API**: FastAPI + Celery + LangGraph, on a Hetzner VPS
- **LLM**: Claude Haiku via the Anthropic API
- **WhatsApp**: self-hosted Evolution API
- **Database**: Supabase Postgres + pgvector + Auth + Storage
- **Payments**: Asaas
- **IaC**: Terraform (Hetzner + AWS)
- **CI/CD**: GitHub Actions

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full topology, the
deviations from the original plan, and the rationale for each choice.

## Repository layout

```
.
├── apps/
│   ├── api/                # FastAPI service (agent + REST + webhooks)
│   └── web/                # Next.js dashboard
├── db/
│   └── migrations/         # SQL migrations (run via Supabase or psql)
├── infra/
│   └── terraform/          # IaC for VPS, secrets, DNS
├── packages/               # Shared TypeScript types (future)
├── docker-compose.yml      # Local dev stack
├── Makefile                # Common dev commands
├── .env.example            # Documented environment variables
└── ARCHITECTURE.md
```

## Quick start (local dev)

Prerequisites: Docker 24+, Node 20+, pnpm 9+, Python 3.11+.

```bash
cp .env.example .env
make up           # postgres + redis + evolution + api + worker
make migrate      # apply SQL migrations
make web-dev      # Next.js dev server on :3000
```

The API listens on `:8000`, the dashboard on `:3000`, Evolution on `:8080`.

### Don't have an Evolution API key yet?

Set `WHATSAPP_PROVIDER=stub` in `.env` and skip the evolution container.
The `StubProvider` mocks every external WhatsApp call -- you can develop,
test, and demo the entire pipeline without a real WhatsApp account:

```bash
echo "WHATSAPP_PROVIDER=stub" >> .env
make up-stub        # postgres + redis + api + worker (no evolution)
make migrate
make seed           # demo tenant + FAQ rows
make demo           # runs an end-to-end conversation through the stub
```

When you do get the gateway working, flip `WHATSAPP_PROVIDER=evolution`
and restart -- no other code changes needed. See
[`ARCHITECTURE.md` §2.9](./ARCHITECTURE.md#29-whatsapp-provider-abstraction-port--adapters)
for the rationale.

## Tests

```bash
make test         # pytest in apps/api
make web-test     # vitest in apps/web (when added)
```

## Security

Encaixe is a public multi-tenant SaaS (public dashboard, public webhook, an
internet-reachable Postgres pooler), so isolation and access control are the
core of the hardening.

**Authentication (fail-closed).** Dashboard JWTs are verified before any claim
is trusted: locally with `SUPABASE_JWT_SECRET` (HS256, signature + expiry) when
set, otherwise against Supabase's authoritative `/auth/v1/user`. There is no
"decode without verifying" fallback, and the rate limiter derives its per-tenant
key from the same verified claims.

**Multi-tenant isolation.** `tenant_id` is validated as a UUID and applied via
parametrized `set_config` (no string interpolation into SQL). Every tenant-scoped
query, including agent history and opt-out reads, filters by `tenant_id`. RLS is
FORCEd (migration `0004`); for it to bind on the API path the app must connect as
the dedicated non-owner role documented in that migration.

**OAuth callback.** The Google Calendar callback requires an authenticated
session and verifies the user's membership in the target tenant before writing
any secret, closing the unauthenticated cross-tenant write.

**Secrets at rest.** Integration OAuth tokens are encrypted with AES-256-GCM
(`APP_ENCRYPTION_KEY`) using a format shared byte-for-byte between the Python API
and the Next.js callback, so a token written by either side is readable by the
other. Encryption activates only when the key is set (legacy plaintext rows keep
working during migration).

**Webhook.** The Evolution webhook authenticates (constant-time compare,
fail-closed on a missing token) before the body is read or parsed, caps the body
at 256 KB, and the API refuses to boot in production without a strong token.

**Abuse control.** Per-tenant rate limiting for verified callers, per-IP
otherwise, and a per-contact daily cap on agent turns so one contact cannot burn
a tenant's LLM budget. Untrusted client messages are fenced (`<mensagem_cliente>`)
and the model is told to treat them as data.

**Transport.** The dashboard ships CSP/`X-Frame-Options`/HSTS headers; the API
CORS layer uses an explicit `CORS_ALLOWED_ORIGINS` allowlist (no wildcard).

### Operational follow-ups (not automatable in code)

- Rotate every secret that was ever in a working-tree `.env` (Postgres password,
  Supabase service role, Anthropic, Voyage, Evolution key/token).
- Set `SUPABASE_JWT_SECRET`, `APP_ENCRYPTION_KEY`, and a strong
  `EVOLUTION_WEBHOOK_TOKEN` in the platform env; re-encrypt existing integration
  rows and test the calendar connect/refresh flow once the key is set.
- Create the non-owner `encaixe_app` DB role (migration `0004`) and point
  `DATABASE_URL` / `DATABASE_URL_SYNC` at it.
- Run `make test` and the plan's verification checklist before deploying: the
  webhook and JWT paths are intentionally stricter (fail-closed) now.

## Deploy

- Dashboard: connect the repo to Vercel, point it at `apps/web`.
- API + Worker + Evolution + Redis: `terraform apply` in
  `infra/terraform/environments/prod` provisions the VPS and pushes the
  Compose stack via cloud-init.
- Database: Supabase project created manually, migrations run via
  `make migrate-prod`.

## License

Proprietary. © 2026 Arthur Viegas.
