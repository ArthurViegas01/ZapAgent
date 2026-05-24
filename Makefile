# ZapAgent — common development commands.

.PHONY: help up down up-stub logs ps build api-shell db-shell migrate migrate-002 test test-local test-api test-integration smoke-local fmt lint web-dev web-build demo seed clean

COMPOSE := docker compose

help:
	@echo "ZapAgent — make targets"
	@echo "  make up           Start the full local stack (postgres, redis, evolution, api, worker)"
	@echo "  make up-stub      Start without evolution; uses WHATSAPP_PROVIDER=stub"
	@echo "  make down         Stop the stack and remove containers"
	@echo "  make logs         Tail logs from all services"
	@echo "  make ps           Show running containers"
	@echo "  make build        Rebuild the api image"
	@echo "  make api-shell    Bash inside the api container"
	@echo "  make db-shell     psql into the local postgres"
	@echo "  make migrate      Apply SQL migrations to local postgres"
	@echo "  make seed         Insert a demo tenant + FAQ rows for the demo flow"
	@echo "  make demo         Run the StubProvider end-to-end conversation demo"
	@echo "  make test         Run pytest inside the api container"
	@echo "  make test-local   Run pytest from the host (uses .env, no docker)"
	@echo "  make test-integration  Run tenant-isolation tests against real Postgres"
	@echo "  make smoke-local       Hit /health, /ready locally — verify the stack is alive"
	@echo "  make fmt          Format Python with ruff"
	@echo "  make lint         ruff + mypy"
	@echo "  make web-dev      Start the Next.js dev server"
	@echo "  make web-build    Build the Next.js app"
	@echo "  make clean        Remove volumes and caches"

up:
	$(COMPOSE) up -d --build

up-stub:
	$(COMPOSE) up -d --build postgres redis api worker

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build api worker

api-shell:
	$(COMPOSE) exec api bash

db-shell:
	$(COMPOSE) exec postgres psql -U zapagent -d zapagent

migrate:
	$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 \
		-f /migrations/0001_init.sql
	$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 \
		-f /migrations/0002_fix_rls_for_js_client.sql
	$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 \
		-f /migrations/0003_billing_trial.sql

seed:
	$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 \
		-f /migrations/seed_demo.sql

demo:
	$(COMPOSE) exec api python -m scripts.demo_stub_conversation

test:
	$(COMPOSE) exec api pytest -q

test-local:
	cd apps/api && pytest -q

# Smoke test the locally-running stack — same script used in production.
# Web URL defaults to localhost:3000; if you didn't `pnpm dev`, the two
# WEB checks will fail (expected). API checks should always pass when
# `make up` (or `make up-stub`) succeeded.
smoke-local:
	python scripts/smoke_test_prod.py \
		--api-url http://localhost:8000 \
		--web-url http://localhost:3000

# Integration tests need a live Postgres+pgvector. Apply both migrations
# idempotently first so tests can run on a fresh DB or one that already
# went through 0001 alone.
test-integration:
	-$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 -f /migrations/0001_init.sql
	-$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 -f /migrations/0002_fix_rls_for_js_client.sql
	-$(COMPOSE) exec -T postgres psql -U zapagent -d zapagent \
		-v ON_ERROR_STOP=1 -f /migrations/0003_billing_trial.sql
	$(COMPOSE) exec api pytest -m integration -v

fmt:
	$(COMPOSE) exec api ruff check --fix src tests
	$(COMPOSE) exec api ruff format src tests

lint:
	$(COMPOSE) exec api ruff check src tests
	$(COMPOSE) exec api mypy src

web-dev:
	cd apps/web && pnpm dev

web-build:
	cd apps/web && pnpm build

clean:
	$(COMPOSE) down -v
	rm -rf apps/api/.pytest_cache apps/api/.mypy_cache apps/api/.ruff_cache
