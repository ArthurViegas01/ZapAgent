###############################################################################
# ZapAgent — Railway Infrastructure
#
# Provisions the full backend stack on Railway:
#   • zapagent-api      FastAPI service (Dockerfile prod target)
#   • zapagent-worker   Celery worker (same image, different CMD)
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

resource "railway_project" "zapagent" {
  name        = "zapagent"
  description = "ZapAgent — WhatsApp AI assistant SaaS"
}

# ---------------------------------------------------------------------------
# Redis plugin (managed by Railway)
# ---------------------------------------------------------------------------

resource "railway_plugin" "redis" {
  project_id      = railway_project.zapagent.id
  name            = "zapagent-redis"
  plugin_type     = "redis"
}

# ---------------------------------------------------------------------------
# Evolution API service
# ---------------------------------------------------------------------------

resource "railway_service" "evolution" {
  project_id = railway_project.zapagent.id
  name       = "zapagent-evolution"

  source_image = "atendai/evolution-api:latest"

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
  }

  depends_on = [railway_service.api, railway_plugin.redis]
}

# ---------------------------------------------------------------------------
# FastAPI service
# ---------------------------------------------------------------------------

resource "railway_service" "api" {
  project_id = railway_project.zapagent.id
  name       = "zapagent-api"

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
    EVOLUTION_API_URL       = "https://${railway_service.evolution.default_domain}"
    EVOLUTION_API_KEY       = var.evolution_api_key
    GOOGLE_OAUTH_CLIENT_ID  = var.google_oauth_client_id
    GOOGLE_OAUTH_CLIENT_SECRET = var.google_oauth_client_secret
    GOOGLE_OAUTH_REDIRECT_URI  = var.google_oauth_redirect_uri
  }

  depends_on = [railway_plugin.redis, railway_service.evolution]
}

# ---------------------------------------------------------------------------
# Celery worker service (same repo, different start command)
# ---------------------------------------------------------------------------

resource "railway_service" "worker" {
  project_id = railway_project.zapagent.id
  name       = "zapagent-worker"

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
