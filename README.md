# ZapAgent

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

## Deploy

- Dashboard: connect the repo to Vercel, point it at `apps/web`.
- API + Worker + Evolution + Redis: `terraform apply` in
  `infra/terraform/environments/prod` provisions the VPS and pushes the
  Compose stack via cloud-init.
- Database: Supabase project created manually, migrations run via
  `make migrate-prod`.

## License

Proprietary. © 2026 Arthur Viegas.
