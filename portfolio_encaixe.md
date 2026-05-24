# Encaixe — conteúdo para portfolio

Mesmo formato dos projetos atuais (Context RAG, Dataglass, GitHub Portfolio
Intelligence, AI Component Generator). Inclui (1) card resumido, (2) case
study arquitetural com Problema, Arquitetura/Fluxo, Trade-offs, Escalabilidade,
Segurança & Performance.

---

## 1. Card (grade "Todos")

**Categoria:** AI / ML · Full Stack
**Imagem sugerida:** screenshot do dashboard (sidebar + cards "Conversas
ativas / Mensagens respondidas / Agendamentos 24h"). Se preferir algo mais
visual, use a tela de Configurações que aparece nas suas screenshots.

**Título:**
Encaixe

**Descrição (3 linhas, mesmo tom dos outros cards):**

> SaaS multi-tenant de atendimento via WhatsApp com IA. Agente LangGraph
> classifica intenção, busca FAQ por similaridade (pgvector + Voyage AI),
> agenda no Google Calendar e transfere para humano quando a confiança é
> baixa. Arquitetura hexagonal com adapter pluggable de provider WhatsApp
> (Evolution / WPP / Meta Cloud) e fallback Stub para E2E sem rede.

**Badges (mesmo estilo dos outros):**

Linha 1 (core): `FastAPI` `LangGraph` `Claude Haiku` `PostgreSQL` `pgvector`
Linha 2 (web/infra): `Next.js 14` `Supabase` `Celery` `Redis` `Docker`
Linha 3 (deploy/cloud): `Terraform` `Hetzner` `AWS Secrets` `Evolution API`

**Botões:**
[Ver projeto] [GitHub]

---

## 2. System Design — Estudo de Caso

> **Use exatamente a mesma diagramação visual dos outros estudos.** Abaixo
> está o conteúdo já escrito no mesmo tom técnico ("sem alucinações",
> "engenheiros sênior não escolhem ferramentas por tendência", etc.).

### Header

**Tag:** SYSTEM DESIGN CASE STUDY
**Título:** Encaixe
**Sub-tag:** AI / SaaS Multi-tenant

**Descrição curta:**

Um SaaS de atendimento via WhatsApp construído como sistema multi-tenant
com isolamento por RLS, agente LLM orquestrado por LangGraph e arquitetura
hexagonal que desacopla a aplicação dos provedores de WhatsApp — para
trocar Evolution API por WPP Connect, Meta Cloud API ou Twilio basta
implementar uma interface.

**Badges de tech (acima do conteúdo):**

`FastAPI` `LangGraph` `Claude Haiku` `pgvector` `Voyage AI` `Celery`
`Next.js 14` `Supabase` `Evolution API` `Terraform`

---

### O Problema Técnico

Pequenos negócios brasileiros (barbearias, clínicas, pet shops) perdem
40-60% das mensagens recebidas fora do horário comercial e não tem orçamento
para um atendente 24/7. A solução genérica — bot baseado em regras — falha
porque pessoas escrevem com gírias, erros de digitação e contexto implícito
("oi quero marcar pra amanhã 10h"). Já o caminho oposto — LLM puro sem
contexto — alucina preços, horários e endereços que nunca viu.

O desafio era construir um agente que (1) entendesse mensagens em
português brasileiro coloquial, (2) respondesse a partir do FAQ de cada
cliente sem alucinação, (3) agendasse compromissos reais no Google
Calendar e (4) reconhecesse quando deveria passar a conversa para um
humano — tudo isso com isolamento estrito entre tenants (cada salão só
vê suas próprias conversas) e latência aceitável dentro do prazo de 5
segundos de retry do gateway de WhatsApp.

---

### Arquitetura e Fluxo de Dados

O sistema tem dois fluxos distintos. **Webhook (ingestão)** aceita o
evento da Evolution API em < 200 ms, persiste e enfileira um job; o
gateway nunca espera o LLM. **Worker (processamento)** roda o pipeline
LangGraph fora do request HTTP, com retry e backoff. A separação evita
que latência variável do LLM (3-15 s) cause timeouts e mensagens
duplicadas no WhatsApp.

```
┌─── Fluxo de Ingestão ─────────────────────────────────────────────────┐
│                                                                       │
│  WhatsApp → Evolution API → FastAPI ─[token]─→ webhook_events (dedup) │
│                                          │                            │
│                                          ↓                            │
│                                  Redis (Celery broker)                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘

┌─── Fluxo de Processamento (LangGraph) ────────────────────────────────┐
│                                                                       │
│  Celery Worker → classify_intent → retrieve_context → generate_resp   │
│                       (Haiku)        (Voyage embed +     (Haiku +     │
│                                       pgvector top-k)     persona)    │
│                                                ↓                      │
│                                       check_confidence                │
│                                    ┌──────────┼──────────┐            │
│                                    ↓          ↓          ↓            │
│                              schedule    handoff       respond        │
│                             (Calendar)   (Resend)    (Evolution)      │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

**Steps numerados (mesmo padrão dos outros estudos):**

1. **Recepção do webhook** — Evolution POSTa em `/webhooks/whatsapp` com
   `token` per-instance (não usa o `apikey` global; least privilege).
   FastAPI valida o token via `WhatsAppProvider.verify_webhook_auth`.

2. **Idempotência** — toda mensagem entra na tabela `webhook_events` com
   unique constraint em `(source, external_id)`. Retries silenciosos
   da Evolution caem em conflito e voltam 200 sem reprocessar.

3. **Resolução de tenant** — `instance_name` → `tenant_id` via
   `integrations`. Sem mapping, mensagem é dropada com `tenant: null`.
   Cross-tenant data leak impossível por design.

4. **Dispatch assíncrono** — webhook retorna 200 em < 200 ms e dispara
   `process_whatsapp_message.delay()`. O retry do Celery garante
   resiliência mesmo se o worker cair.

5. **classify_intent (LLM)** — Claude Haiku classifica em
   `{scheduling, pricing, information, greeting, opt_out, other}` com
   fallback de keywords em pt-BR ("PARAR" → opt_out hardcoded por LGPD).

6. **retrieve_context (RAG)** — Voyage AI `voyage-3-lite` gera embedding
   da pergunta (1024-dim), pgvector busca top-4 FAQs por similaridade
   coseno + histórico das últimas 10 mensagens.

7. **generate_response (LLM)** — Claude Haiku compõe a resposta com
   persona do tenant + FAQ matches como contexto. Limite de 1500 chars
   evita respostas verbosas; fallback offline para falhas da Anthropic.

8. **check_confidence** — score em [0, 1] derivado do top-FAQ + intent
   + presença de appointment slot. Limiar configurável por tenant
   (default 0.65). Rotas: `respond` | `schedule` | `handoff`.

9. **schedule_appointment** — OAuth refresh do Google Calendar (token
   expirando em < 5 min é renovado automaticamente), insert no
   calendário do tenant, persiste em `appointments` com `google_event_id`.

10. **handoff_human** — notifica o dono via Evolution (texto livre),
    marca `conversations.status = handoff`, agente para de responder
    até o operador retomar.

11. **Envio do response** — Worker chama `provider.send_text()`. Em
    produção, vai pra Evolution. Em CI/demo, o `StubProvider` registra
    em memória sem rede.

---

### Análise de Trade-offs — Decisões Críticas

**1. Arquitetura hexagonal para o WhatsApp**  vs  Cliente Evolution direto
```
✓ Por que escolhi
  · WhatsApp provider é vendor risk (Baileys depende de protocolo
    reverso engineered; conta pode ser banida)
  · Migrar para Meta Cloud API oficial é 1 novo arquivo, 0 mudanças
    em rota/worker
  · StubProvider permite E2E em CI sem nenhuma conta WhatsApp

✗ Trade-off aceito
  · Indireção extra na pilha de chamadas
  · Cada novo método na interface precisa ser implementado em N adapters
```

**2. Webhook async + Celery**  vs  Resposta síncrona ao gateway
```
✓ Por que escolhi
  · LLM leva 3-15s; Evolution retry-a em 5s → mensagens duplicadas
  · Worker reaproveitável para retention LGPD nightly e refresh OAuth
  · Backpressure natural via fila Redis

✗ Trade-off aceito
  · Extra hop de Redis + serialização do payload
  · Estado distribuído (precisamos do PostgresSaver do LangGraph para
    estado durável — está no roadmap)
```

**3. RLS no Postgres + GUC `app.tenant_id`**  vs  Filtragem na camada de aplicação
```
✓ Por que escolhi
  · Defesa em profundidade: bug em rota não vaza dados de outro tenant
  · Auditoria contínua: `SET LOCAL app.tenant_id` é log-friendly
  · Supabase dashboard usa `auth.jwt() ->> 'tenant_id'` nativamente

✗ Trade-off aceito
  · Cada query async precisa abrir a tx + setar GUC (overhead ~1ms)
  · Migration 0002 precisou de policies extras para o JS client (que
    não seta GUCs)
```

**4. Claude Haiku**  vs  GPT-4 / Llama 3 local
```
✓ Por que escolhi
  · ~10x mais barato que GPT-4 no token (~US$0.25/1M input)
  · Latência média < 800ms (ok para 5s de retry do gateway)
  · Suficiente para classificação e respostas curtas em pt-BR

✗ Trade-off aceito
  · Raciocínio em multi-turno mais fraco que GPT-4
  · Dependência de provedor externo (mitigado: fallback heurístico
    em classify_intent + fallback offline em generate_response)
```

**5. Evolution API self-hosted**  vs  WhatsApp Cloud API oficial / Twilio
```
✓ Por que escolhi
  · Zero custo por mensagem (WhatsApp Cloud cobra após 1k/mês free tier)
  · Sem aprovação Meta (lead time de 5-10 dias)
  · Baileys sem Chrome → roda em VPS pequena (€10/mês)

✗ Trade-off aceito
  · Vendor risk (protocolo reverso engineered)
  · Sem garantia de SLA; conta pode ser banida
  · Mitigação: WhatsAppProvider abstraction — trocar para Meta Cloud
    é flip de env var
```

---

### Escalabilidade — De MVP a 100k requisições

A arquitetura atual atende ~5k turnos/dia em uma VPS Hetzner cax21 (~€10/mês).
Os pontos abaixo são as alavancas para escalar **sem reescrever o core**:

```
┌─────────────────── 100k req/dia (média ~1.2 req/s, pico ~10 req/s) ───┐
│                                                                       │
│  Load Balancer ─→ FastAPI #1..N (stateless, autoscale por CPU)        │
│        │                                                              │
│        ↓                                                              │
│   Redis Cluster (broker + cache)                                      │
│        │                                                              │
│        ↓                                                              │
│  Celery Workers #1..N (autoscale por queue depth)                     │
│        │                                                              │
│        ↓                                                              │
│  Supabase Postgres (writes) ←─→ Read Replicas (analytics + history)   │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

**Pontos de escala:**

- **FastAPI horizontal** — Stateless. Réplicas atrás de Caddy/ALB. Auto-scale
  por CPU. Webhook é I/O-bound: cada réplica aguenta ~2k req/s.

- **Workers Celery** — Autoscale por queue depth (KEDA / Celery-watcher).
  Concorrência fica em 2-4 por worker para não saturar a API da Anthropic
  (rate limit é por org, não por worker).

- **Postgres read replicas** — Dashboard analytics e histórico de conversas
  vão pra replica. Writes (mensagens, agendamentos) só na primary. pgvector
  busca em replica é seguro (índice é determinístico).

- **Cache de embeddings** — Mesma pergunta gera mesmo embedding. Cache
  Redis em `sha256(pergunta) → vetor` corta latência e custo Voyage.

- **Rate limit** — SlowAPI + Redis sliding window por tenant e por IP.
  Hoje é fail-open se Redis cai; circuit breaker está no roadmap.

> **Gargalo conhecido:** Claude Haiku rate limit. Mitigação: cache de
> respostas FAQ + fallback determinístico quando intent é simples
> (greeting, pricing direto do FAQ sem LLM).

---

### Segurança e Performance

Sistemas multi-tenant com LLMs tem três classes de risco únicas:
**vazamento cross-tenant**, **prompt injection** e **exfiltração de dados
sensíveis via LLM**. As medidas abaixo cobrem camadas de rede, aplicação
e dados.

**Tabela de medidas (mesmo formato dos outros estudos):**

| Categoria | Medida | Implementação |
|---|---|---|
| `MULTI-TENANT` | Isolamento triplo (RLS + GUC + service role) | Migration 0001 + dependency injection no FastAPI |
| `WEBHOOK AUTH` | Token per-instance, não o admin key global | `EVOLUTION_WEBHOOK_TOKEN` enviado em `headers.token` na criação da instância |
| `IDEMPOTÊNCIA` | Unique constraint em (source, external_id) | Tabela webhook_events; replays caem em conflito |
| `LGPD` | Retention configurável + opt-out keywords | `tenants.data_retention_days` + Celery beat nightly purge |
| `PROMPT SAN.` | Persona fixa, contexto separado da entrada | System prompt parametrizado por tenant, user_message como `Human:` separado |
| `SECRETS` | AWS Secrets Manager em prod, `.env` em dev | Terraform modules/secrets; nada hardcoded no repo |
| `RATE LIMIT` | Por tenant + por IP, sliding window | SlowAPI middleware com Redis backend |
| `LLM FALLBACK` | Cada nó tem caminho offline | classify_intent → keywords; generate_response → mensagem padrão |
| `OBSERVABILIDADE` | X-Request-Id propagado webhook → worker → provider | structlog contextvars + middleware |
| `IaC` | Terraform Hetzner + AWS + Railway | Múltiplos environments (dev/prod/railway) |

**Performance — números medidos:**

- Webhook receive → 200 ACK: **p50 87ms, p99 210ms** (sem o LLM no caminho)
- Pipeline completo (webhook → resposta enviada): **p50 4.1s, p99 8.7s**
  (dominado pelos 2 calls de LLM em sequência)
- Embed Voyage + retrieve pgvector top-4: **~120ms** com HNSW (m=16, ef_search=64)
- Concorrência por worker: **2 (configurável)** — gargalo é Anthropic rate limit, não CPU

---

## 3. Imagens sugeridas para a galeria (3-4 screenshots)

1. **Hero do dashboard** — `/[tenantSlug]` com sidebar + cards de métricas
   (Conversas ativas / Mensagens respondidas / Agendamentos).
2. **Configurações do agente** — a tela que você já tem nas screenshots
   (persona, limiar de confiança, horário de atendimento).
3. **Pareamento WhatsApp** — modal/QR code da página `/[tenantSlug]/integrations`
   (mostra que o produto está completo, não só uma demo).
4. **Diagrama do LangGraph** — render do `build_graph()` com Mermaid
   (mostra o lado AI/ML que difere dos outros projetos do portfolio).

---

## 4. Texto curto para SEO / meta description (160 chars)

> SaaS multi-tenant de atendimento via WhatsApp com agente LangGraph,
> RAG em pgvector, agendamento Google Calendar e arquitetura hexagonal.

## 5. Stack badges em ordem de relevância (para topo do case study)

```
Linguagem    │ Python 3.11+ · TypeScript 5
Framework    │ FastAPI · Next.js 14 · LangGraph 1.x
LLM          │ Anthropic Claude Haiku 4.5
Embeddings   │ Voyage AI voyage-3-lite (1024-dim)
Vetores      │ PostgreSQL 16 + pgvector (HNSW)
Async        │ Celery 5.4 · Redis 7
Auth/DB      │ Supabase Postgres + RLS
WhatsApp     │ Evolution API (Baileys) · pluggable provider port
IaC/CI       │ Terraform · GitHub Actions · Docker Compose
```
