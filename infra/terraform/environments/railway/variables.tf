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
