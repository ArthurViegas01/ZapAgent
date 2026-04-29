# Terraform — ZapAgent infra

Two providers do the heavy lifting:

- **Hetzner Cloud** — provisions the VPS that runs Docker Compose with the
  FastAPI service, Celery worker, Redis, and Evolution API.
- **AWS** — Secrets Manager for production secrets and ECR (later) for the
  API image registry.

Supabase (Postgres, Auth, Storage) is provisioned manually via the dashboard
and tracked in this repo only by reference (project id, ref keys go into
secrets manager). A community Supabase Terraform provider exists but is not
yet stable enough for prod.

## Layout

```
infra/terraform/
├── modules/
│   ├── vps/             # Hetzner cloud server + cloud-init that boots Compose
│   ├── secrets/         # AWS Secrets Manager bundle for the env
│   └── dns/             # (future) Cloudflare DNS records
└── environments/
    ├── dev/             # Personal sandbox; tfstate in S3 dev bucket
    └── prod/            # Production; tfstate in S3 prod bucket with locking
```

## Workflow

```bash
cd infra/terraform/environments/dev
terraform init
terraform plan -out=plan.out
terraform apply plan.out
```

`terraform.tfvars` is gitignored — copy `terraform.tfvars.example` and fill
in API tokens. Production tfvars are loaded from AWS Secrets Manager via
`terraform -var-file=...` in CI.

## What's intentionally missing in v0.1

- Cloudflare DNS module (we'll add when we move off the temporary domain).
- Database module (Supabase has no first-party provider, see note above).
- Backups for the VPS (Hetzner snapshots are configured outside Terraform).
