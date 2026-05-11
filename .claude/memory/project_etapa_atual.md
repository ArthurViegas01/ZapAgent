---
name: ZapAgent — estado da implementação (sessão 2026-05-10)
description: Provider abstraction completo, 73 testes passando, Evolution destravado via Stub
type: project
---

**Refactor sênior concluído (2026-05-10):** WhatsApp foi extraído atrás de uma porta `WhatsAppProvider` em `apps/api/src/integrations/whatsapp/`. Adapters: `EvolutionProvider` (prod) e `StubProvider` (E2E sem rede).

**O que está pronto:**
- Todos os 6 nós LangGraph funcionando (classify, retrieve, generate, check_confidence, schedule_appointment, handoff_human) com fallbacks offline.
- Webhook receiver provider-agnóstico em `apps/api/src/api/webhooks/whatsapp.py`.
- Router `routers/integrations.py` usa `provider.create_session/get_session/delete_session`. Para Evolution faz `poll_for_qr` extra.
- Worker `_send_whatsapp_reply` chama `provider.send_text`.
- Auth de webhook migrou de `apikey` global → `token` per-instance (least privilege).
- Settings tem `whatsapp_provider: Literal["evolution","stub"]` + `evolution_webhook_base_url`.
- `/health` (liveness) + `/ready` (DB ping + provider check); `RequestIdMiddleware` propaga `X-Request-Id` para structlog contextvars.
- `make demo`, `make seed`, `make up-stub`.
- Docs: CHANGELOG.md, ROADMAP.md; ARCHITECTURE.md §2.9 documenta port+adapters.
- 73 testes passam (incluindo 12 novos em tests/integrations/test_whatsapp_provider.py).

**Bugs corrigidos do diff em flight:**
- `check_confidence` voltou a exigir `state.get("appointment")` para rotear a `schedule`.
- Removido `pool=None` morto em `_send_whatsapp_reply`.
- `os.environ.get(...)` em integrations.py removido.

**Why:** Usuário esperou >1 semana por chave Evolution e WPP Connect falhou. Provider abstraction destrava trabalho local + facilita troca futura.

**How to apply:** Próxima sessão pode focar em (1) PostgresSaver real para LangGraph, (2) OpenTelemetry, (3) Sentry, (4) backups Supabase, (5) circuit breaker para rate limit. Ver ROADMAP.md.
