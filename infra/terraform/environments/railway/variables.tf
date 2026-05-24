variable "railway_token" {
  description = "Railway API token (Settings → Tokens)"
  type        = string
  sensitive   = true
}

variable "github_repo" {
  description = "GitHub repo in 'owner/repo' format"
  type        = string
  # e.g. "arthurpviegas/zapagent"
}

variable "deploy_branch" {
  description = "Git branch to deploy"
  type        = string
  default     = "main"
}

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

variable "supabase_url" {
  description = "Supabase project URL"
  type        = string
}

variable "supabase_anon_key" {
  description = "Supabase anon/public key"
  type        = string
  sensitive   = true
}

variable "supabase_service_role_key" {
  description = "Supabase service role key"
  type        = string
  sensitive   = true
}

variable "supabase_db_url" {
  description = "Supabase direct Postgres connection string (postgresql://...)"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# AI services
# ---------------------------------------------------------------------------

variable "anthropic_api_key" {
  description = "Anthropic API key"
  type        = string
  sensitive   = true
}

variable "voyage_api_key" {
  description = "Voyage AI key for embeddings"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Evolution API
# ---------------------------------------------------------------------------

variable "evolution_api_key" {
  description = "Shared secret for Evolution API authentication"
  type        = string
  sensitive   = true
}

variable "evolution_webhook_token" {
  description = <<-EOT
    Per-instance token Evolution sends in the `token` header on every
    webhook event (least-privilege; we never give Evolution our admin
    apikey for webhook routing). The API verifies via
    `EvolutionProvider.verify_webhook_auth` against `EVOLUTION_WEBHOOK_TOKEN`.
    Pick a strong random string distinct from `evolution_api_key`.
  EOT
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

variable "sentry_dsn" {
  description = <<-EOT
    Sentry project DSN for the api + worker services. Leave empty to
    disable Sentry; the wiring in `core/observability.py` no-ops when
    unset. Form: https://<key>@<org>.ingest.sentry.io/<project>
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "sentry_traces_sample_rate" {
  description = "Fraction of requests sampled for performance tracing (0.0 disables)."
  type        = number
  default     = 0.1
}

# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

variable "google_oauth_client_id" {
  description = "Google OAuth client ID"
  type        = string
}

variable "google_oauth_client_secret" {
  description = "Google OAuth client secret"
  type        = string
  sensitive   = true
}

variable "google_oauth_redirect_uri" {
  description = "OAuth redirect URI (must match Google Cloud Console)"
  type        = string
  # e.g. "https://zapagent.netlify.app/auth/google-calendar/callback"
}
