variable "hcloud_token" {
  description = "Hetzner Cloud API token."
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS region for Secrets Manager."
  type        = string
  default     = "sa-east-1"
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the VPS."
  type        = string
}

variable "repo_url" {
  description = "Git URL of the ZapAgent monorepo."
  type        = string
}

variable "git_ref" {
  description = "Branch the dev VPS should track."
  type        = string
  default     = "main"
}

variable "env_blob" {
  description = "Contents of the .env file rendered onto the VPS."
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Domain name pointing at the dev VPS."
  type        = string
  default     = "dev.zapagent.com.br"
}

variable "app_secrets" {
  description = "Map of secret keys/values that get bundled into Secrets Manager."
  type        = map(string)
  sensitive   = true
  default     = {}
}
