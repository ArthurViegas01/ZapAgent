---
name: ZapAgent — estado da implementação (Etapa 1 em andamento)
description: O que está pronto e o que falta no MVP do ZapAgent
type: project
---

**Scaffold completo** (96 arquivos): docs raiz, apps/api, apps/web, db/migrations, infra/terraform, docker-compose.

**Etapa 1 — Nós reais do grafo (em andamento, sessão 2026-04-28):**
- classify_intent: ainda heurística de keywords (pt-BR) — LLM call pendente
- retrieve_context: IMPLEMENTADO async com voyage-3-lite + pgvector + histórico 10 msgs; fallback stub quando sem pool/key
- generate_response: IMPLEMENTADO async com Claude Haiku; prompt parametrizado por tenant_settings; fallback offline elegante; 22/22 testes passando
- schedule_appointment: placeholder (slot-filling + Google Calendar pendente)
- handoff_human: placeholder (Evolution API + Resend pendente)

**Etapas pendentes:** 2 (API/webhooks), 3 (Dashboard), 4 (CI/CD/prod), 5 (GTM), 6 (v0.2).

**Why:** Foco em destravar testes realistas; classify_intent com LLM é o próximo passo natural.

**How to apply:** Próxima sessão começa por classify_intent real (Claude Haiku + JSON schema + fallback keyword OPT_OUT hardcoded) e depois Etapa 2 (webhook receiver).
