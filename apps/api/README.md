# apps/api

FastAPI service that hosts the LangGraph orchestrator, REST endpoints
consumed by the Next.js dashboard, and the Evolution API webhook receiver.

## Layout

```
src/
├── main.py                 # FastAPI factory + lifespan
├── core/                   # config, logging, security, dependencies
├── db/                     # SQLAlchemy engine + session, models
├── agent/                  # LangGraph orchestrator
│   ├── state.py            # typed AgentState
│   ├── graph.py            # StateGraph builder
│   └── nodes/              # one file per node
├── api/                    # HTTP routers
│   ├── webhooks/           # Evolution + Asaas webhooks
│   └── routers/            # /tenants, /faq, /conversations, ...
├── services/               # domain services (calendar, whatsapp, billing)
├── worker/                 # Celery app + tasks
└── schemas/                # Pydantic request/response models

tests/
├── agent/                  # unit tests for each LangGraph node
├── api/                    # endpoint tests with httpx.AsyncClient
└── conftest.py             # fixtures
```

## Running tests

```bash
pytest -q                   # full suite
pytest tests/agent -q       # only the LangGraph nodes
pytest -k classify_intent   # filter by name
```
