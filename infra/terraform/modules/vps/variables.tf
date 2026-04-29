variable "environment" {
  description = "Deployment environment: dev | staging | prod."
  type        = string
}

variable "server_type" {
  description = "Hetzner server type. cax21 is a good baseline for the MVP."
  type        = string
  default     = "cax21"
}

variable "location" {
  description = "Hetzner location code (e.g. fsn1, nbg1, hel1, ash, hil)."
  type        = string
  default     = "ash"
}

variable "ssh_public_key" {
  description = "SSH public key authorized to log into the server as root."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to SSH in."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "repo_url" {
  description = "Git URL of the ZapAgent monorepo."
  type        = string
}

variable "git_ref" {
  description = "Branch or tag to check out on the server."
  type        = string
  default     = "main"
}

variable "env_blob" {
  description = "Contents of the .env file delivered to the server. Pulled from Secrets Manager in CI."
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Primary domain pointing at the VPS (used by Caddy in cloud-init)."
  type        = string
}

variable "data_volume_size_gb" {
  description = "Size of the attached data volume for postgres / evolution storage."
  type        = number
  default     = 20
}
