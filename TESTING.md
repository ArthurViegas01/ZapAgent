# Encaixe — Roteiro de Testes Locais

Guia reproduzível para validar a stack completa antes do deploy. Dois caminhos,
do mais barato (sem dependências externas) ao mais completo (WhatsApp real).

> **Pré-requisitos** comuns: Docker 24+, Make, Python 3.11+, ~2 GB livres em disco.
> Tudo abaixo roda contra o `docker-compose.yml` da raiz. Nenhum comando precisa
> ser executado direto na sua máquina host além do `make`.

## Sumário

- [Caminho A — Stub provider](#caminho-a--stub-provider-sem-whatsapp-real) — 5 min, valida pipeline LangGraph offline
- [Caminho B — Evolution real](#caminho-b--evolution-real-whatsapp-pessoal) — 15-30 min, valida fluxo completo
- [Suíte de testes automatizada](#suíte-de-testes-automatizada)
- [O que cada caminho NÃO cobre](#o-que-cada-caminho-não-cobre)
- [Triagem de falhas comuns](#triagem-de-falhas-comuns)

---

## Caminho A — Stub provider (sem WhatsApp real)

Valida a pipeline LangGraph (classify → retrieve → generate → check → schedule/handoff)
sem depender do Evolution API nem de chaves Anthropic/Voyage. Os nodes têm
fallback determinístico offline. Roda em ~5 min.

### A.1 Setup

```bash
cp .env.example .env
echo "WHATSAPP_PROVIDER=stub" >> .env
make up-stub        # postgres + redis + api + worker (sem evolution)
make migrate        # aplica migrations 0001 + 0002 + 0003
make seed           # tenant demo + 3 FAQ rows; subscription_status=active
```

Aguarde ~10s após `make up-stub` (postgres + redis fazem healthcheck antes da API subir).

### A.2 Smoke test dos endpoints

```bash
make smoke-local
# OU manualmente:
python scripts/smoke_test_prod.py \
  --api-url http://localhost:8000 \
  --web-url http://localhost:3000   # opcional, se você subiu o web também
```

**Esperado:**
- `[PASS] API /health` → 200 OK
- `[PASS] API /ready` → status `ready`, db=true, provider=stub
- (sem web rodando, os checks WEB falham — esperado se você só está testando a API)

### A.3 Demo do agente end-to-end (offline)

```bash
make demo
```

Saída esperada (extrato):

```
[user]  Oi, tudo bem?
[bot ]  Olá! Como posso ajudar você hoje?
        next_action=respond confidence=0.40

[user]  Quero saber o horario de funcionamento
[bot ]  Atendemos de segunda a sabado, das 9h as 19h.
        next_action=respond confidence=0.92

[user]  Quero agendar amanha as 10h
[bot ]  Claro! Para agendar, me informe a data e o horario de sua preferencia.
        next_action=respond confidence=0.40

[user]  PARAR
[bot ]  Tudo bem! Removemos voce da nossa lista de mensagens. ...
        next_action=respond confidence=0.40
```

> **Atenção:** este demo invoca `build_graph` diretamente — NÃO passa pelo
> webhook handler nem pelo gate de billing. Para testar essas camadas, vá
> para A.4 e A.5.

### A.4 Testar webhook + Celery (caminho de produção)

O caminho real é: webhook recebe → persiste → enfileira Celery → worker roda grafo → resposta volta. Para exercitar isso com o Stub:

```bash
# Em um terminal, observe o worker:
docker compose logs -f worker

# Em outro:
curl -X POST http://localhost:8000/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -H "token: changeme" \
  -d '{
    "event":"stub.inbound",
    "instance":"demo-instance",
    "phone":"5511999990000",
    "text":"Quero saber o horario",
    "id":"smoke_001"
  }'
```

> O `token: changeme` casa com `EVOLUTION_WEBHOOK_TOKEN` default — em `.env`
> use o valor que você setou ali (Stub respeita o mesmo header).

**Esperado** (no log do worker):
- `worker.task.started` com `tenant_id=00000000-0000-0000-0000-0000000d3070`
- `worker.task.done` com `next_action=respond`
- `stub.send_text` com a resposta

**Esperado** (resposta da API): `{"ok":true,"queued":true}`

Você precisa primeiro inserir uma integration mapeando `demo-instance → tenant demo`:

```bash
docker compose exec postgres psql -U zapagent -d zapagent -c "
INSERT INTO integrations (tenant_id, kind, external_id, status, config)
VALUES (
  '00000000-0000-0000-0000-0000000d3070',
  'whatsapp', 'demo-instance', 'connected', '{}'::jsonb
) ON CONFLICT DO NOTHING;
"
```

### A.5 Testar billing gate (trial / suspended)

```bash
# 1. Verifique o estado atual (deve ser 'active' por causa do seed):
docker compose exec postgres psql -U zapagent -d zapagent -c "
  SELECT slug, subscription_status, trial_ends_at FROM tenants;
"

# 2. Force trial expirado:
docker compose exec postgres psql -U zapagent -d zapagent -c "
  UPDATE tenants
     SET subscription_status='trialing', trial_ends_at=NOW() - INTERVAL '1 day'
   WHERE slug='demo';
"

# 3. Repita o curl do A.4. Esperado:
#    - Resposta API: {"ok":true,"skipped":"billing","billing_status":"trialing"}
#    - Log do worker: NÃO há worker.task.started (não enfileirou)
#    - Log da API:   webhook.billing_blocked com reason=trial_expired
#    - Stub recebe send_text com a mensagem "Período de teste encerrado..."

# 4. Force suspended:
docker compose exec postgres psql -U zapagent -d zapagent -c "
  UPDATE tenants SET subscription_status='suspended' WHERE slug='demo';
"
# Refaça o curl → resposta diferente, mensagem "Assinatura pausada..."

# 5. Volte para active (limpeza):
docker compose exec postgres psql -U zapagent -d zapagent -c "
  UPDATE tenants SET subscription_status='active', trial_ends_at=NULL WHERE slug='demo';
"
```

### A.6 (opcional) Subir o dashboard

```bash
cd apps/web
pnpm install
cp ../../.env.example .env.local   # ajuste NEXT_PUBLIC_* conforme necessário
pnpm dev    # http://localhost:3000
```

Para login local você precisa de um projeto Supabase configurado (mesmo que de testes).
Sem isso, o dashboard renderiza mas não autentica. Para validação só do agente,
pule esta etapa.

---

## Caminho B — Evolution real (WhatsApp pessoal)

Valida o fluxo ponta-a-ponta com WhatsApp real. Use seu número pessoal ou um
número descartável; o Evolution API roda WhatsApp Web headless (Baileys).

### B.1 Setup

```bash
cp .env.example .env
# .env: WHATSAPP_PROVIDER=evolution (default)
#       EVOLUTION_API_KEY=<gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"`>
#       EVOLUTION_WEBHOOK_TOKEN=<outro secrets.token_urlsafe(32) — diferente>
#       ANTHROPIC_API_KEY=<sua chave>  (opcional, mas sem isso o LLM cai em fallback)
#       VOYAGE_API_KEY=<sua chave>     (opcional, sem isso retrieve_context retorna [])

make up           # postgres + redis + evolution + api + worker
make migrate
make seed
```

### B.2 Conectar WhatsApp via dashboard

```bash
# Em outro terminal:
cd apps/web && pnpm dev
```

1. Abra `http://localhost:3000`
2. Faça signup (precisa de Supabase configurado em `.env.local`)
3. No onboarding, crie o tenant `demo` (ou outro)
4. Vá em **Integrações → Conectar WhatsApp**
5. Escaneie o QR com o WhatsApp do seu celular (WhatsApp → Aparelhos conectados → Conectar dispositivo)

**Esperado:** status flip de `pending` → `connected` em ~10s após scan.

> **Se o QR não aparecer:** confira logs `docker compose logs evolution` — se
> ver "Baileys" + erros de handshake, o pin do `apps/evolution/Dockerfile`
> (Baileys 6.7.9) pode ter quebrado. Esse é o bug documentado no Dockerfile.

### B.3 Mensagem real

De OUTRO celular, mande para o número conectado:

> "Qual o horário de funcionamento?"

**Esperado em ~5-15s:**
- Auto-reply chega no WhatsApp
- Dashboard → Conversas: a conversa aparece com os dois turnos
- Dashboard → Visão geral: contador "Mensagens respondidas" incrementa

> **Se você está testando com um número WhatsApp moderno (privacy mode ligado,
> padrão em contas BR novas):** o JID inbound chega como `@lid` em vez de
> `@s.whatsapp.net`. Para o reply funcionar, o `lid_pipe.py` embutido na
> imagem do Evolution precisa estar interceptando o `sender_pn`. Confira:
>
> ```bash
> docker logs encaixe-evolution | grep "\[lid_pipe\]"
> # Esperado:
> #   [lid_pipe] started; mirroring child=/bin/bash redis=redis://redis:6379/0 ttl=86400s
> # E após cada mensagem @lid recebida:
> #   [lid_pipe] cached msg_id=... phone=55XXXXXX total=N
> ```
>
> Se não vir o `cached`, sua mensagem não passou pelo intercept e o reply vai
> dar 400. Veja se o REDIS_URL está no env do serviço evolution
> (`docker compose config evolution | grep -i redis`).

Depois teste saudação simples (regression do per-intent confidence rules):

> "Oi"

**Esperado:** auto-reply educado (não handoff humano). Antes do fix de
2026-05-24 isso caía em "vou chamar um atendente" porque GREETING não
match nenhuma FAQ.

Depois teste agendamento:

> "Quero agendar amanhã às 14h."

**Esperado:**
- Slot-filling extrai date+time → confirmação
- Se Google Calendar estiver conectado: evento criado no calendário
- `SELECT * FROM appointments WHERE tenant_id=...;` mostra a linha

### B.4 Smoke do circuit breaker do rate-limit

O middleware fail-open em blip Redis, mas após 5 falhas consecutivas
abre o circuito e responde 503 com `Retry-After`. Para forçar localmente:

```bash
# 1. Pause o Redis (mantém a estrutura, só corta a conexão):
docker compose pause redis

# 2. Faça 6 requests pra um endpoint NÃO exempt (webhooks são exempt!):
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/tenants
done
# Esperado: 5 respostas (fail-open: 401/403/etc), 6a vira 503

# 3. Logs da API mostram a transição:
docker compose logs api | grep rate_limit.breaker
# Esperado:
#   rate_limit.breaker_opened consecutive_errors=5 cooldown_seconds=30.0
#   rate_limit.breaker_open_reject path=/v1/tenants

# 4. Recupera:
docker compose unpause redis
# Após 30s o breaker half-open, próxima request bem-sucedida fecha:
#   rate_limit.breaker_half_open
#   rate_limit.breaker_closed consecutive_errors_before=5
```

---

## Suíte de testes automatizada

```bash
make test               # pytest unit (dentro do container)
make test-integration   # pytest com Postgres real (tenant isolation + RLS)
```

CI roda ambos automaticamente em push/PR. Localmente, rode antes de commit.

```bash
# Frontend
cd apps/web && pnpm test
```

---

## O que cada caminho NÃO cobre

| Caminho | Cobre | NÃO cobre |
|---|---|---|
| A.3 `make demo` | LangGraph offline, slot-filling, opt-out, fallback texts | Webhook, Celery, billing gate, DB persistence |
| A.4 curl webhook + Stub | Webhook handler, dedup, tenant resolution, Celery, billing gate, persistência | LLM real (Anthropic), embedding real (Voyage), WhatsApp real |
| A.5 billing gate | trial expired, suspended, mensagens pt-BR ao cliente | – |
| B Evolution real | TUDO: WhatsApp real, QR pairing, mensagens reais, GCal | OAuth Google Calendar end-to-end (precisa configurar separado) |
| `make test` | Nodes LangGraph isolados, parsers Evolution/Stub, billing gate unitário, rate-limit circuit breaker, @lid parser | Postgres real, RLS |
| `make test-integration` | RLS + GUC, isolation cross-tenant, query helpers reais, regressão de event-loop por task (per_task_pool_scoping) | Webhook → Celery → reply (precisa B) |

---

## Triagem de falhas comuns

| Sintoma | Causa provável | Como confirmar |
|---|---|---|
| `make up` trava em "waiting for postgres" | Volume antigo com schema incompatível | `make clean && make up` |
| API responde `503 Database not available` em rotas autenticadas | Pool não inicializou (DSN errado em `.env`) | `docker compose logs api \| grep db.pool` |
| Webhook responde `200 {"tenant":null}` | Integração faltando no DB para o `instance_name` | `SELECT * FROM integrations WHERE external_id='<seu>';` |
| Webhook responde `200 {"skipped":"billing"}` | Trial expirado ou tenant suspended | `SELECT subscription_status, trial_ends_at FROM tenants;` |
| QR do WhatsApp não aparece | Baileys quebrou após update Meta | logs `docker compose logs evolution` — procure "noise" ou "handshake"; testar com `apt-get install` no Dockerfile |
| Agente sempre responde fallback genérico | `ANTHROPIC_API_KEY` vazio | `docker compose exec api env \| grep ANTHROPIC` |
| FAQ retorna 0 matches mesmo com seed | `VOYAGE_API_KEY` vazio (retrieve_context retorna stubs) | logs API: `retrieve_context.stub reason=no_voyage_key` |
| `make test` ok mas `make test-integration` skipa tudo | Postgres do compose não está up | `docker compose ps postgres` |

---

## Limpeza

```bash
make down       # para a stack mas mantém volumes
make clean      # para + remove volumes (perde dados locais)
```
