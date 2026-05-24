###############################################################################
# Encaixe — Railway Infrastructure
#
# Provisions the full backend stack on Railway:
#   • encaixe-api      FastAPI service (Dockerfile prod target)
#   • encaixe-worker   Celery worker (same image, different CMD)
#   • zapagent-evo      Evolution API (WhatsApp bridge)
#   • Redis             Railway plugin (managed Redis)
#
# Frontend (Next.js) is deployed to Netlify separately.
# Postgres is Supabase-managed — no Railway DB needed.
#
# Usage:
#   cd infra/terraform/environments/railway
#   cp terraform.tfvars.example terraform.tfvars   # fill in secrets
#   terraform init
#   terraform apply
###############################################################################

terraform {
  required_version = ">= 1.6"

  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.3"
    }
  }

  # Uncomment to store state remotely (recommended for teams):
  # backend "s3" {
  #   bucket = "zapagent-tfstate"
  #   key    = "railway/terraform.tfstate"
  #   region = "sa-east-1"
  # }
}

provider "railway" {
  token = var.railway_token
}

# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

resource "railway_project" "encaixe" {
  name        = "encaixe"
  description = "Encaixe — WhatsApp AI assistant SaaS"
}

# ---------------------------------------------------------------------------
# Redis plugin (managed by Railway)
# ---------------------------------------------------------------------------

resource "railway_plugin" "redis" {
  project_id      = railway_project.zapagent.id
  name            = "encaixe-redis"
  plugin_type     = "redis"
}

# ---------------------------------------------------------------------------
# Evolution API service
# ---------------------------------------------------------------------------

resource "railway_service" "evolution" {
  project_id = railway_project.zapagent.id
  name       = "encaixe-evolution"

  # IMPORTANT: build from `apps/evolution/Dockerfile` (NOT the official
  # `atendai/evolution-api:latest` image). The official image pins an old
  # @whiskeysockets/baileys whose noise-protocol keys are out of date —
  # WebSocket connects (101) but the encrypted handshake never completes
  # and no QR is generated. Our Dockerfile inherits from the official
  # image and installs Baileys 6.7.9 (last CJS-compatible release that
  # works with Evolution 2.2.x). This is the same fix already proven
  # locally via docker-compose. See `apps/evolution/Dockerfile`.
  source {
    repo            = var.github_repo
    root_directory  = "apps/evolution"
  }

  build_config {
    builder         = "dockerfile"
    dockerfile_path = "Dockerfile"
  }

  volume {
    mount_path = "/evolution/instances"
  }
}

locals {
  # Evolution Prisma uses its own schema so tables do not collide with the app public schema.
  evolution_database_connection_uri = (
    strcontains(var.supabase_db_url, "?") ?
    "${var.supabase_db_url}&schema=evolution_api" :
    "${var.supabase_db_url}?schema=evolution_api"
  )
}

resource "railway_variable_collection" "evolution_vars" {
  project_id      = railway_project.zapagent.id
  service_id      = railway_service.evolution.id
  environment_id  = railway_project.zapagent.default_environment_id

  variables = {
    SERVER_TYPE             = "http"
    SERVER_PORT             = "8080"
    AUTHENTICATION_API_KEY  = var.evolution_api_key
    DATABASE_ENABLED        = "true"
    DATABASE_PROVIDER       = "postgresql"
    DATABASE_CONNECTION_URI = local.evolution_database_connection_uri
    CACHE_REDIS_ENABLED     = "true"
    CACHE_REDIS_URI         = "${railway_plugin.redis.url}/3"
    CACHE_REDIS_PREFIX_KEY  = "evolution"
    # Webhook points to the API service — Railway internal DNS
    WEBHOOK_GLOBAL_URL              = "https://${railway_service.api.default_domain}/webhooks/whatsapp"
    WEBHOOK_GLOBAL_ENABLED          = "true"
    # Must match API: single POST /webhooks/whatsapp (not per-event paths).
    WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS = "false"
    WEBHOOK_EVENTS_QRCODE_UPDATED   = "true"
    WEBHOOK_EVENTS_MESSAGES_UPSERT  = "true"
    WEBHOOK_EVENTS_CONNECTION_UPDATE = "true"

    # ----------------------------------------------------------------
    # @lid sender_pn intercept (lid_pipe.py, embedded in the Evolution
    # image — see apps/evolution/Dockerfile). Modern Brazilian WA
    # accounts hide the real phone behind an @lid JID and Evolution
    # drops the sender_pn webhook field; lid_pipe reads stdout and
    # writes `lid_pn:{msg_id}` to Redis db 0. The API webhook looks
    # the key up when it sees an @lid contact. Without these env vars
    # the script falls into passthrough mode (Evolution still works,
    # but @lid replies fail with 400).
    # ----------------------------------------------------------------
    REDIS_URL        = "${railway_plugin.redis.url}/0"
    LID_TTL_SECONDS  = "86400"
  }

  depends_on = [railway_service.api, railway_plugin.redis]
}

# ---------------------------------------------------------------------------
# FastAPI service
# ---------------------------------------------------------------------------

resource "railway_service" "api" {
  project_id = railway_project.zapagent.id
  name       = "encaixe-api"

  source {
    repo   = var.github_repo
    branch = var.deploy_branch
  }

  build_config {
    builder          = "dockerfile"
    dockerfile_path  = "apps/api/Dockerfile"
    build_target     = "prod"
  }

  start_command = "uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 2"
  healthcheck_path = "/health"
}

resource "railway_variable_collection" "api_vars" {
  project_id     = railway_project.zapagent.id
  service_id     = railway_service.api.id
  environment_id = railway_project.zapagent.default_environment_id

  variables = {
    ENVIRONMENT             = "production"
    DATABASE_URL_SYNC       = var.supabase_db_url
    REDIS_URL               = railway_plugin.redis.url
    CELERY_BROKER_URL       = "${railway_plugin.redis.url}/1"
    CELERY_RESULT_BACKEND   = "${railway_plugin.redis.url}/2"
    SUPABASE_URL            = var.supabase_url
    SUPABASE_ANON_KEY       = var.supabase_anon_key
    SUPABASE_SERVICE_ROLE_KEY = var.supabase_service_role_key
    ANTHROPIC_API_KEY       = var.anthropic_api_key
    VOYAGE_API_KEY          = var.voyage_api_key

    # ----------------------------------------------------------------
    # WhatsApp provider — explicit. Default in settings.py is
    # "evolution" but pinning the env var keeps surprises out of
    # production. Switch to "stub" only for emergency triage.
    # ----------------------------------------------------------------
    WHATSAPP_PROVIDER       = "evolution"
    EVOLUTION_API_URL       = "https://${railway_service.evolution.default_domain}"
    EVOLUTION_API_KEY       = var.evolution_api_key

    # Token Evolution echoes back on every webhook (header `token: ...`).
    # API verifies via `EvolutionProvider.verify_webhook_auth`. Without
    # this, the webhook handler accepts any caller — see settings.py
    # default of "changeme" which is intentionally invalid in prod.
    EVOLUTION_WEBHOOK_TOKEN = var.evolution_webhook_token

    # Base URL Evolution POSTs to. The default in settings.py points at
    # `http://api:8000/...` (docker-compose internal DNS) which does NOT
    # resolve on Railway — without overriding it, the QR generates but
    # no inbound message ever reaches the agent.
    EVOLUTION_WEBHOOK_BASE_URL = "https://${railway_service.api.default_domain}/webhooks/whatsapp"

    # ----------------------------------------------------------------
    # Google Calendar OAuth — redirect URI must match the Netlify URL
    # in Google Cloud Console *exactly* (scheme + host + path).
    # ----------------------------------------------------------------
    GOOGLE_OAUTH_CLIENT_ID     = var.google_oauth_client_id
    GOOGLE_OAUTH_CLIENT_SECRET = var.google_oauth_client_secret
    GOOGLE_OAUTH_REDIRECT_URI  = var.google_oauth_redirect_uri

    # ----------------------------------------------------------------
    # Sentry — empty DSN = no-op in code (core/observability.py).
    # SENTRY_RELEASE pulls the SHA Railway injects on every build so
    # error grouping per release works out of the box. The literal
    # ${"$"}{...} is a Terraform escape; Railway sees a plain "$VAR".
    # ----------------------------------------------------------------
    SENTRY_DSN                = var.sentry_dsn
    SENTRY_TRACES_SAMPLE_RATE = tostring(var.sentry_traces_sample_rate)
    SENTRY_RELEASE            = "$${RAILWAY_GIT_COMMIT_SHA}"
  }

  depends_on = [railway_plugin.redis, railway_service.evolution]
}

# ---------------------------------------------------------------------------
# Celery worker service (same repo, different start command)
# ---------------------------------------------------------------------------

resource "railway_service" "worker" {
  project_id = railway_project.zapagent.id
  name       = "encaixe-worker"

  source {
    repo   = var.github_repo
    branch = var.deploy_branch
  }

  build_config {
    builder         = "dockerfile"
    dockerfile_path = "apps/api/Dockerfile"
    build_target    = "prod"
  }

  start_command = "celery -A src.worker.celery_app worker --loglevel=INFO --concurrency=2"
}

resource "railway_variable_collection" "worker_vars" {
  project_id     = railway_project.zapagent.id
  service_id     = railway_service.worker.id
  environment_id = railway_project.zapagent.default_environment_id

  # Worker needs identical env vars to the API.
  variables = railway_variable_collection.api_vars.variables

  depends_on = [railway_variable_collection.api_vars]
}
