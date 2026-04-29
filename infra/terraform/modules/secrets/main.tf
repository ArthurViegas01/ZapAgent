# AWS Secrets Manager bundle for ZapAgent. The application secrets are stored
# as a single JSON blob; CI pulls and decodes the secret to materialize a .env
# before delivering it to the VPS via the vps module's `env_blob` input.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "/${var.environment}/zapagent/app"
  description             = "ZapAgent application secrets bundle (${var.environment})."
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = {
    project     = "zapagent"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode(var.app_secrets)
}
