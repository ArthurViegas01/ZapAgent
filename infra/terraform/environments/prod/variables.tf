variable "hcloud_token" {
  type      = string
  sensitive = true
}

variable "aws_region" {
  type    = string
  default = "sa-east-1"
}

variable "ssh_public_key" {
  type = string
}

variable "ops_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0", "::/0"]
}

variable "repo_url" {
  type = string
}

variable "git_ref" {
  type    = string
  default = "main"
}

variable "env_blob" {
  type      = string
  sensitive = true
}

variable "domain_name" {
  type    = string
  default = "app.zapagent.com.br"
}

variable "app_secrets" {
  type      = map(string)
  sensitive = true
  default   = {}
}
