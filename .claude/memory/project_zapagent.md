---
name: ZapAgent — contexto e stack
description: Stack completa, arquitetura e estado atual do projeto ZapAgent
type: project
---

ZapAgent é um SaaS multi-tenant de atendimento via WhatsApp com agendamento inteligente.

**Stack:**
- `apps/api/` — FastAPI 3.11+, LangGraph 1.x, Anthropic SDK, voyage-3-lite (pgvector), Celery, asyncpg, structlog
- `apps/web/` — Next.js 14 App Router, TypeScript, Tailwind, Supabase SSR
- `db/` — PostgreSQL + pgvector + pgcrypto, 8 tabelas, RLS com GUC `app.tenant_id`
- `infra/terraform/` — Hetzner VPS + AWS Secrets Manager
- `docker-compose.yml` — postgres (pgvector), redis, evolution-api v2.1.1, api, worker

**Grafo LangGraph (6 nós):**
classify_intent → retrieve_context → generate_response → check_confidence → [schedule_appointment | handoff_human | END]

**Why:** Clientes são pequenos negócios (barbearia, clínica, pet shop) que precisam de atendimento 24/7 no WhatsApp sem contratar atendentes.

**How to apply:** Ao sugerir código, usar padrões já estabelecidos (TypedDict AgentState, nós retornando partial state, async def para nós com I/O externo).
