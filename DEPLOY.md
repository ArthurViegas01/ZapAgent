# ZapAgent — Deploy Guide

## Architecture

```
Netlify (free)          Railway (paid min.)         Supabase (free)
┌──────────────┐        ┌──────────────────────┐    ┌──────────────┐
│  Next.js     │──API──▶│  FastAPI (zapagent-  │    │  PostgreSQL  │
│  Frontend    │        │  api)                │───▶│  Auth        │
└──────────────┘        │  Celery Worker       │    └──────────────┘
                        │  Evolution API       │
                        │  Redis (plugin)      │
                        └──────────────────────┘
                                  ▲
                        GitHub Actions CI/CD
                        Terraform (IaC)
```

---

## 1. Prerequisites

- Railway account (any paid plan — needed for volumes on Evolution)
- Netlify account (free)
- GitHub repo pushed with this codebase
- Supabase project already running

---

## 2. Railway Setup (via Terraform)

Terraform provisions all Railway services automatically.

```bash
cd infra/terraform/environments/railway

# Install Railway Terraform provider
terraform init

# Copy and fill in your secrets
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars with your values

# Preview changes
terraform plan

# Deploy everything
terraform apply
```

Terraform creates:
- `zapagent-api` — FastAPI service
- `zapagent-worker` — Celery worker
- `zapagent-evolution` — Evolution API (WhatsApp bridge)
- Redis plugin (managed)

After `terraform apply`, note the output URLs:
```
api_url = "https://zapagent-api-production.up.railway.app"
evolution_url = "https://zapagent-evolution-production.up.railway.app"
```

---

## 3. Netlify Setup (Frontend)

### Option A — Netlify UI (easier)

1. Go to [app.netlify.com](https://app.netlify.com) → **Add new site → Import from Git**
2. Select your GitHub repo
3. Set build settings:
   - **Base directory**: `apps/web`
   - **Build command**: `npm run build`
   - **Publish directory**: `apps/web/.next`
4. Add environment variables (Site settings → Environment variables):

```
NEXT_PUBLIC_SUPABASE_URL         = https://oodfxbrbawcnromvhjga.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY    = sb_publishable_...
NEXT_PUBLIC_API_URL              = https://zapagent-api-XXX.up.railway.app
SUPABASE_SERVICE_ROLE_KEY        = sb_secret_...
GOOGLE_OAUTH_CLIENT_ID           = 799398426606-...
GOOGLE_OAUTH_CLIENT_SECRET       = GOCSPX-...
GOOGLE_OAUTH_REDIRECT_URI        = https://your-site.netlify.app/auth/google-calendar/callback
```

5. Install the Next.js plugin: **Plugins → Next.js Runtime**

### Option B — GitHub Actions (automated, already configured)

Add these secrets to your GitHub repo (Settings → Secrets):

```
NETLIFY_AUTH_TOKEN    (from Netlify: User settings → Applications → New access token)
NETLIFY_SITE_ID       (from Netlify: Site settings → General → Site ID)
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
API_URL
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
```

Every push to `main` deploys automatically.

---

## 4. GitHub Actions Secrets (for CI/CD)

Add all of these to GitHub repo Settings → Secrets → Actions:

```
# Railway
RAILWAY_TOKEN              (Railway: Settings → Tokens → New Token)

# Supabase
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_DB_URL            (Settings → Database → Connection string → URI)

# Netlify
NETLIFY_AUTH_TOKEN
NETLIFY_SITE_ID

# App secrets
ANTHROPIC_API_KEY
VOYAGE_API_KEY
EVOLUTION_API_KEY
API_URL                    (Railway API service URL)
GH_REPO                    (e.g. "arthurpviegas/zapagent")

# Google OAuth
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
```

---

## 5. Database Migrations

Supabase migrations run from the Supabase dashboard or CLI:

```bash
# Install Supabase CLI
npm install -g supabase

# Link to your project
supabase link --project-ref oodfxbrbawcnromvhjga

# Run migrations
supabase db push
```

Or paste `db/migrations/0001_init.sql` directly in the Supabase SQL editor.

---

## 6. Post-Deploy Checklist

- [ ] `GET https://your-api.railway.app/health` returns `{"status":"ok"}`
- [ ] WhatsApp connects and QR appears (test in dashboard)
- [ ] Google Calendar OAuth redirect URI updated in Google Cloud Console
- [ ] Supabase Auth → URL Configuration: add Netlify URL to redirect URLs
- [ ] Evolution API key matches between Railway env vars and Netlify env vars

---

## 7. Local Development

```bash
# Start full stack
docker compose up

# API hot-reloads automatically on file changes
# Frontend
cd apps/web && npm run dev
```

---

## Cost estimate (minimum)

| Service       | Cost         |
|---------------|--------------|
| Netlify       | Free         |
| Supabase      | Free         |
| Railway       | ~$5/month    |
| Anthropic     | Pay-per-use  |
| Voyage AI     | Free tier    |
| **Total**     | **~$5/month** |
