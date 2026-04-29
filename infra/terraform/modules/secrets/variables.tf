variable "environment" {
  description = "dev | staging | prod"
  type        = string
}

variable "app_secrets" {
  description = "Map of secret values stored as a single JSON blob."
  type        = map(string)
  sensitive   = true
}
