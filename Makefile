# ZapAgent — common development commands.

.PHONY: help up down up-stub logs ps build api-shell db-shell migrate migrate-002 test test-local test-api fmt lint web-dev web-build demo seed clean

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
	@echo "  make fmt          Format Python with ruff"
	@echo "  make lint         ruff + mypy"
	@echo "  make web-dev      Start the Next.js dev server"
	@echo "  make web-build    Build the Next.js app"
	@echo "  make clean        Remove volumes and caches"

up:
	$(COMPOSE) up -d --build

up-stub:
	WHATSAPP_PROVIDER=stub $(COMPOSE) up -d --build postgres redis api worker

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
