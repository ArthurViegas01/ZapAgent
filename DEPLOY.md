# Encaixe — Deploy Runbook (Railway + Netlify)

This is a **step-by-step runbook** to take Encaixe from a clean repo to a
public URL serving a paying pilot. Every step is a checkbox; tick it
before moving on. Estimated total: **3–4 hours of clock time** the first
time, ~30 min after the secrets exist.

> Architecture summary (see `ARCHITECTURE.md` for the why)
>
>     Netlify (free)        ──HTTPS──▶  Railway (paid min ~$5/mo)
>     Next.js dashboard                  ├ encaixe-api      (FastAPI)
>                                        ├ encaixe-worker   (Celery)
>                                        ├ encaixe-evolution (WhatsApp)
>                                        └ encaixe-redis    (managed plugin)
>                                                  │
>                                                  ▼
>                                          Supabase (free)
>                                          Postgres + Auth + pgvector

The Hetzner+Vercel path documented in earlier commits remains in the
repo (`infra/terraform/environments/prod`) for the eventual §4 migration
once the pilot generates revenue; **this runbook deploys Railway+Netlify**.

---

## 0. Prerequisites

Tick each before proceeding.

- [ ] **GitHub** account with this repo pushed to `main`
- [ ] **Railway** account on a paid plan (any tier — volumes require paid)
- [ ] **Netlify** account (free)
- [ ] **Supabase** project, with migrations `0001`, `0002`, `0003` applied (see §3)
- [ ] **Anthropic** API key (Claude Haiku) — https://console.anthropic.com
- [ ] **Voyage AI** API key (`voyage-3-lite` embeddings) — https://dash.voyageai.com
- [ ] **Google Cloud** OAuth client with Calendar scope (Calendar API enabled)
- [ ] **Sentry** project (optional but recommended — leaving SENTRY_DSN empty disables cleanly)
- [ ] Sanity: `cd apps/api && make test && make smoke-local` green locally before
      pushing the deploy — CI runs the same and a red CI does NOT trip an
      auto-deploy (see §6).

> `terraform` CLI is NOT a prereq right now — see §4. The Railway IaC at
> `infra/terraform/environments/railway/main.tf` doesn't validate against
> the current provider schema, so the deploy is dashboard-driven for now.

### What ships in production

The Terraform stack provisions four pieces, all `encaixe-*`-prefixed (the
project's internal codename):

| Component | Where | What it does |
|---|---|---|
| `encaixe-redis` | Railway managed plugin | Celery broker, rate-limit buckets, `lid_pn:*` cache |
| `encaixe-evolution` | Railway service, built from `apps/evolution/Dockerfile` | WhatsApp gateway (Baileys 6.7.9) **with `lid_pipe.py` as PID 1** intercepting `sender_pn` (see §4.1) |
| `encaixe-api` | Railway service, built from `apps/api/Dockerfile` (prod target) | FastAPI: REST, webhooks, rate-limit middleware with circuit breaker |
| `encaixe-worker` | Railway service, same image, Celery start command | LangGraph agent runner |
| dashboard | Netlify, `apps/web` | Next.js operator UI |
| Postgres | Supabase | `tenants`/`messages`/`faq_items`/etc, pgvector |

---

## 1. Generate secrets you don't have yet

> **About Evolution API:** Evolution runs **self-hosted** inside our
> stack — both locally (`docker-compose.yml` → `evolution` service) and
> in production (Terraform Railway provisions it from
> `apps/evolution/Dockerfile`). You do **not** need an Evolution account
> nor approval from their hosted SaaS at evolution-api.com. The two
> secrets below are shared secrets **you generate yourself**; nothing
> needs to be registered with a third party.

Two new secrets we introduced for the production hardening pass:

```bash
# Evolution admin key (one-shot strong random) — shared between the
# API service and the Evolution container; used by API → Evolution
# control-plane calls (create_session, send_text, …).
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Evolution webhook token (DIFFERENT from the admin key — least privilege)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save both to your password manager — you'll paste them into `terraform.tfvars`
in §4 and as GitHub secrets in §6.

---

## 2. Configure Google OAuth

The redirect URI you register here must match exactly what you'll feed
both Terraform (Railway) and Netlify in the next steps. Decide your
Netlify site name now (e.g. `zapagent.netlify.app`) and use it everywhere.

- [ ] Google Cloud Console → APIs & Services → Credentials → **Create OAuth client ID**
- [ ] Application type: Web application
- [ ] **Authorized redirect URIs** → add:
      `https://<YOUR-NETLIFY-SITE>.netlify.app/auth/google-calendar/callback`
- [ ] Save Client ID + Client Secret to your password manager.
- [ ] Enable the **Google Calendar API** on the same project (APIs & Services → Library).

---

## 3. Apply database migrations to Supabase

```bash
# Easiest path: open Supabase → SQL Editor and paste each file in order:
#   db/migrations/0001_init.sql
#   db/migrations/0002_fix_rls_for_js_client.sql
#   db/migrations/0003_billing_trial.sql

# Or via the CLI:
supabase link --project-ref <YOUR-REF>
supabase db push   # picks up all 3 migrations from db/migrations/
```

- [ ] Verify pgvector is enabled: `SELECT * FROM pg_extension WHERE extname='vector';`
- [ ] Verify RLS is on: `SELECT relname FROM pg_class WHERE relrowsecurity AND relkind='r';`
      (should include `tenants`, `users`, `faq_items`, `conversations`, `messages`,
      `appointments`, `integrations`, `webhook_events`)
- [ ] Grab the Postgres connection string: Settings → Database → Connection string → **URI**
      Format: `postgresql://postgres.<REF>:<PWD>@<HOST>:5432/postgres`

---

## 4. Provision Railway (manual UI — Terraform is broken)

> **Heads-up (2026-05-24):** `infra/terraform/environments/railway/main.tf`
> was authored against an API that the `terraform-community-providers/railway`
> provider never shipped. `terraform validate` fails on every version we
> tried (0.1 through 0.6.2) because `railway_plugin`, `railway_variable_collection`,
> the nested `source { }`/`build_config { }` blocks, and the
> `start_command`/`healthcheck_path` attrs simply do not exist in this
> provider. Until someone rewrites the IaC against the real schema
> (`source_repo`, `config_path`, per-variable `railway_variable`, external
> Redis since the plugin resource doesn't exist), the path forward is the
> Railway dashboard. That's the runbook below. Track it in the ROADMAP as
> "rewrite Terraform Railway module".

You'll create one project and four services / one Redis through the
Railway dashboard. Plan on ~30 min the first time, ~5 min for subsequent
changes (Railway auto-redeploys on git push once the services are wired
to GitHub).

### 4.1 Generate a Railway API token (only used by GitHub Actions)

- [ ] Railway → Account Settings → Tokens → **Create New Token**
- [ ] Save as `RAILWAY_TOKEN` in your password manager (will go into
      GitHub secrets in §6 — Actions uses it to trigger redeploys via
      `railway up`)

### 4.2 Create the project + Redis

- [ ] Railway dashboard → **New Project** → name it `encaixe`
- [ ] Inside the project → **+ New** → **Database** → **Add Redis**
      → name the service `encaixe-redis`
- [ ] Click the Redis service → **Variables** tab → copy the value of
      `REDIS_URL` (it looks like `redis://default:<PWD>@<HOST>.railway.internal:6379`).
      You'll paste it into the other services below.

### 4.3 Create the Evolution service

- [ ] Project → **+ New** → **GitHub Repo** → pick `arthurpviegas/zapagent` (or your fork)
- [ ] Settings → name it `encaixe-evolution`
- [ ] Settings → Source → **Root Directory** = `apps/evolution`
- [ ] Settings → Build → **Builder** = Dockerfile (auto-detected from `apps/evolution/Dockerfile`)
- [ ] Settings → Networking → **Generate Domain** (Railway gives you `encaixe-evolution-production.up.railway.app`).
      You'll need this URL for the API service below.
- [ ] Settings → Volumes → **+ Volume** → Mount path `/evolution/instances`
      (required so WhatsApp sessions survive restarts)
- [ ] Variables tab — paste these (use the Redis URL from §4.2):

  ```env
  SERVER_TYPE=http
  SERVER_PORT=8080
  AUTHENTICATION_API_KEY=<EVOLUTION_API_KEY from §1>
  DATABASE_ENABLED=true
  DATABASE_PROVIDER=postgresql
  DATABASE_CONNECTION_URI=<your supabase_db_url>?schema=evolution_api
  CACHE_REDIS_ENABLED=true
  CACHE_REDIS_URI=<REDIS_URL from §4.2>/3
  CACHE_REDIS_PREFIX_KEY=evolution
  WEBHOOK_GLOBAL_URL=https://<encaixe-api-domain>/webhooks/whatsapp
  WEBHOOK_GLOBAL_ENABLED=true
  WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=false
  WEBHOOK_EVENTS_QRCODE_UPDATED=true
  WEBHOOK_EVENTS_MESSAGES_UPSERT=true
  WEBHOOK_EVENTS_CONNECTION_UPDATE=true
  REDIS_URL=<REDIS_URL from §4.2>/0
  LID_TTL_SECONDS=86400
  CONFIG_SESSION_PHONE_VERSION=2.3000.1035194821
  LOG_BAILEYS=debug
  ```

  > The last two env vars (`REDIS_URL`, `LID_TTL_SECONDS`) are **required**
  > for `lid_pipe.py` (the @lid intercept inside the Evolution image) to
  > cache `sender_pn`. Without them privacy-mode WhatsApp contacts (most
  > modern BR accounts) can never receive replies. The script falls into
  > passthrough mode silently if the env is missing — Evolution still
  > runs, but every `@lid` reply 400s.

- [ ] **Deploy** — wait for build, check Logs.

### 4.4 Create the API service

- [ ] Project → **+ New** → **GitHub Repo** → same repo
- [ ] Settings → name it `encaixe-api`
- [ ] Settings → Source → leave **Root Directory** empty (build from repo root)
- [ ] Settings → Build → **Dockerfile Path** = `apps/api/Dockerfile`, **Target Stage** = `prod`
- [ ] Settings → Start Command = `uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 2`
- [ ] Settings → Healthcheck Path = `/health`
- [ ] Settings → Networking → **Generate Domain** → save the URL (this is `<api_url>`
      below and replaces `<encaixe-api-domain>` in §4.3 — go back and
      update the Evolution `WEBHOOK_GLOBAL_URL` after this step)
- [ ] Variables tab — paste these:

  ```env
  ENVIRONMENT=production
  DATABASE_URL_SYNC=<your supabase_db_url>
  REDIS_URL=<REDIS_URL from §4.2>
  CELERY_BROKER_URL=<REDIS_URL from §4.2>/1
  CELERY_RESULT_BACKEND=<REDIS_URL from §4.2>/2
  SUPABASE_URL=https://<REF>.supabase.co
  SUPABASE_ANON_KEY=<from §3>
  SUPABASE_SERVICE_ROLE_KEY=<from §3>
  ANTHROPIC_API_KEY=<your anthropic key>
  VOYAGE_API_KEY=<your voyage key>
  WHATSAPP_PROVIDER=evolution
  EVOLUTION_API_URL=https://<encaixe-evolution-domain from §4.3>
  EVOLUTION_API_KEY=<EVOLUTION_API_KEY from §1>
  EVOLUTION_WEBHOOK_TOKEN=<EVOLUTION_WEBHOOK_TOKEN from §1>
  EVOLUTION_WEBHOOK_BASE_URL=https://<encaixe-api-domain>/webhooks/whatsapp
  GOOGLE_OAUTH_CLIENT_ID=<from §2>
  GOOGLE_OAUTH_CLIENT_SECRET=<from §2>
  GOOGLE_OAUTH_REDIRECT_URI=https://<YOUR-NETLIFY-SITE>.netlify.app/auth/google-calendar/callback
  SENTRY_DSN=<optional, blank to disable>
  SENTRY_TRACES_SAMPLE_RATE=0.1
  ```

- [ ] **Deploy**

### 4.5 Create the Celery worker service

Easiest path: **Duplicate** the `encaixe-api` service in the Railway UI
(service → Settings → … → Duplicate), then change two things:

- [ ] Rename to `encaixe-worker`
- [ ] Settings → Start Command = `celery -A src.worker.celery_app worker --loglevel=INFO --concurrency=2`
- [ ] Settings → Healthcheck Path → remove (worker doesn't serve HTTP)
- [ ] Settings → Networking → do NOT generate a domain (internal-only)
- [ ] Variables — copy verbatim from `encaixe-api` (Railway lets you
      reference shared env via `${{encaixe-api.VARNAME}}` if you want to
      avoid duplication, but copy-paste is fine for a pilot)
- [ ] **Deploy**

### 4.6 Verify

- [ ] All four services (`encaixe-redis`, `encaixe-evolution`, `encaixe-api`, `encaixe-worker`) show green/running
- [ ] `curl https://<api_url>/health` → 200
- [ ] `curl https://<api_url>/ready` → `{"status":"ready","db":true,"whatsapp_provider":"evolution"}`
- [ ] Logs on `encaixe-evolution` show **on boot**:
      `[lid_pipe] started; mirroring child=/bin/bash redis=redis://...:6379/0 ttl=86400s`
      — if you don't see it, `REDIS_URL` is missing from §4.3 env vars
      and `@lid` contacts will silently fail in production.
- [ ] Logs on `encaixe-api` show `RateLimitMiddleware` configured (no
      Redis errors on startup)

---

## 5. Deploy frontend on Netlify

### 5.1 First-time site setup (manual)

- [ ] Netlify → **Add new site → Import from Git** → pick the repo
- [ ] **Base directory:** `apps/web`
- [ ] **Build command:** `pnpm install --frozen-lockfile && pnpm run build`
- [ ] **Publish directory:** `apps/web/.next`
- [ ] **Plugins** → install **`@netlify/plugin-nextjs`** (one-click)

### 5.2 Site environment variables

Add under **Site settings → Environment variables**. The same values that
go into GitHub secrets in §6 — pasting them here ensures the Netlify UI
"Trigger redeploy" button works without depending on Actions:

```
NEXT_PUBLIC_SUPABASE_URL          = https://<REF>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY     = sb_publishable_...
NEXT_PUBLIC_API_URL               = <api_url from `terraform output`>
SUPABASE_SERVICE_ROLE_KEY         = sb_secret_...
GOOGLE_OAUTH_CLIENT_ID            = ...
GOOGLE_OAUTH_CLIENT_SECRET        = ...
GOOGLE_OAUTH_REDIRECT_URI         = https://<NETLIFY-SITE>.netlify.app/auth/google-calendar/callback
NEXT_PUBLIC_SENTRY_DSN            = (optional; same project as backend)
```

- [ ] All env vars saved
- [ ] **Trigger deploy** → wait for build success
- [ ] Open the Netlify URL → `/login` page should render

### 5.3 Update Supabase Auth allowed URLs

- [ ] Supabase → Authentication → URL Configuration → **Add** the Netlify URL
      to both **Site URL** and **Redirect URLs**.

---

## 6. GitHub Actions secrets (for CI/CD)

These power the automated re-deploys in `.github/workflows/{api,web,terraform}.yml`.
Settings → Secrets and variables → Actions → New repository secret.

```
# --- Railway ---
RAILWAY_TOKEN                  # same token as terraform.tfvars
GH_REPO                        # arthurpviegas/zapagent

# --- Supabase ---
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_DB_URL

# --- Netlify ---
NETLIFY_AUTH_TOKEN             # User settings → Applications → New token
NETLIFY_SITE_ID                # Site settings → General → Site ID
API_URL                        # api_url from terraform output

# --- App secrets ---
ANTHROPIC_API_KEY
VOYAGE_API_KEY
EVOLUTION_API_KEY              # same as terraform.tfvars
EVOLUTION_WEBHOOK_TOKEN        # same as terraform.tfvars
SENTRY_DSN                     # blank string OK to disable

# --- Google OAuth ---
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
```

- [ ] All 16 secrets present
- [ ] Push a no-op commit to `main` → all three workflows run green

---

## 7. Smoke test — verify the URL is alive

```bash
python scripts/smoke_test_prod.py \
  --api-url $(terraform -chdir=infra/terraform/environments/railway output -raw api_url) \
  --web-url https://<YOUR-NETLIFY-SITE>.netlify.app
```

- [ ] All 4 checks pass: `API /health`, `API /ready`, `WEB /`, `WEB /login`

Optional fifth check requires a tenant + a Supabase JWT (created during
the next step):

```bash
python scripts/smoke_test_prod.py \
  --api-url $API_URL --web-url $WEB_URL \
  --jwt $SUPABASE_JWT --tenant-id $TENANT_ID
```

---

## 8. Create the pilot tenant + connect WhatsApp

This is the moment of truth — proves the entire pipeline works against
a real WhatsApp account.

- [ ] Open the Netlify URL → **Sign up** as the pilot operator
- [ ] Complete onboarding → enter the clinic's business name + phone
- [ ] Open **Integrações** → click **Conectar WhatsApp**
- [ ] Scan the QR with the clinic's WhatsApp Business app
      _(Polling backs off at ~30 polls / 2 min; if QR vanishes before
      you scan, click Disconnect → Connect again and re-scan promptly.)_
- [ ] Status should flip to `connected` within ~10s after the scan
- [ ] Open **Integrações** → **Conectar Google Calendar** → consent flow
- [ ] Open **FAQ** → add at least 3 question/answer pairs (the clinic's most
      common questions)

### 8.1 End-to-end message test

From **another** phone, send a WhatsApp message to the clinic's number:

> "Quero saber qual é o horário de funcionamento."

Expect, within ~5–15s:

- [ ] An auto-reply arrives quoting the FAQ answer
- [ ] In the dashboard → **Conversas**, the conversation appears with both turns
- [ ] In the dashboard → **Visão geral**, the "Mensagens respondidas" counter ticks up

If something fails, debug in this order:

1. Railway → `encaixe-api` logs → look for `webhook.queued` then `worker.task.started`
2. Railway → `encaixe-worker` logs → look for `worker.reply_sent`
3. Supabase SQL Editor:
   ```sql
   SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT 5;
   SELECT * FROM messages       ORDER BY created_at DESC LIMIT 10;
   ```
4. Sentry — if Sentry is wired, the issue will show up grouped by `component:api`
   or `component:worker`.

### 8.2 Scheduling test

> "Quero agendar amanhã às 14h."

Expect:

- [ ] Slot-filling extracts date+time → confirmation message arrives
- [ ] Google Calendar shows a new event titled "Atendimento - 55XXX..." at 14:00 tomorrow
- [ ] `SELECT * FROM appointments WHERE tenant_id = '<TID>';` shows the row

---

## 9. Cost & billing

For the pilot:

- Charge the clinic R$297/mo via Pix manually (no Asaas yet).
- After payment lands, flip the tenant to `active`:
  ```sql
  UPDATE tenants SET subscription_status = 'active'
   WHERE slug = '<clinic-slug>';
  ```
- The dashboard banner will disappear and the subscription gate stops counting down.

A trial that expires before payment will:
1. Stop processing inbound messages.
2. Reply to the customer with a polite "trial encerrado" message in pt-BR.
3. Show a red banner in the dashboard to the operator.

(Tenant `subscription_status = 'past_due'` is the **grace** state — service
continues, banner is orange, operator gets a nudge.)

---

## 10. Rollback

If a deploy is broken in production:

- **Frontend**: Netlify → Deploys → previous deploy → **Publish deploy**.
  Effective in <30s; no DB impact.
- **Backend**: Railway → service → Deployments → previous → **Redeploy**.
  Roughly 1–2 min per service. Migrations are forward-only — never run
  a `DROP TABLE` migration in this layout.

If a **migration** is the problem and you need to undo, restore the
Supabase project from the most recent automatic backup (Supabase →
Database → Backups). RPO is ~24h for free tier.

---

## Cost estimate (post-deploy, monthly)

| Service       | Cost          |
|---------------|---------------|
| Netlify       | Free          |
| Supabase      | Free (Pro $25 once you hit 500 MB or need PITR) |
| Railway       | $5 base + ~$5 metered for the 4 services |
| Anthropic     | ~$2-5 at MVP volume (200–800 turns/mo) |
| Voyage AI     | Free tier covers MVP |
| Sentry        | Free (5k events/mo) |
| **Total**     | **~$15/month** |

Break-even at one paying tenant on the R$297/mo plan.

---

## Appendix — single-file env reference

For the impatient operator, here is every env var that exists in prod
and where it comes from. Anything in `apps/api/src/core/config.py` not
listed here is left at the default and is intentional.

| Env var | Set by | Notes |
|---|---|---|
| `ENVIRONMENT` | Terraform → `api_vars` | always `production` |
| `DATABASE_URL_SYNC` | Terraform | Supabase pooler URL |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Terraform | from `railway_plugin.redis.url` |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Terraform | from `terraform.tfvars` |
| `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` | Terraform |