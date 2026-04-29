terraform {
  required_version = ">= 1.6"

  # Production tfstate is locked. Configure the S3 bucket + DynamoDB table
  # ahead of time and uncomment.
  # backend "s3" {
  #   bucket         = "zapagent-tfstate-prod"
  #   key            = "envs/prod/terraform.tfstate"
  #   region         = "sa-east-1"
  #   dynamodb_table = "zapagent-tfstate-locks"
  #   encrypt        = true
  # }

  required_providers {
    hcloud = { source = "hetznercloud/hcloud", version = "~> 1.48" }
    aws    = { source = "hashicorp/aws",       version = "~> 5.60" }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "aws" {
  region = var.aws_region
}

module "secrets" {
  source      = "../../modules/secrets"
  environment = "prod"
  app_secrets = var.app_secrets
}

module "vps" {
  source = "../../modules/vps"

  environment         = "prod"
  server_type         = "cax31" # bigger box than dev
  location            = "ash"
  ssh_public_key      = var.ssh_public_key
  ssh_allowed_cidrs   = var.ops_cidrs
  repo_url            = var.repo_url
  git_ref             = var.git_ref
  env_blob            = var.env_blob
  domain_name         = var.domain_name
  data_volume_size_gb = 50
}

output "vps_ipv4" {
  value = module.vps.ipv4_address
}

output "secrets_arn" {
  value = module.secrets.secret_arn
}
