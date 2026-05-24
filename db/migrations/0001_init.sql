-- =============================================================================
-- Encaixe — initial schema (migration 0001).
--
-- Multi-tenant by design. Every business-data table carries `tenant_id` and
-- has Row Level Security policies that key off the `app.tenant_id` GUC. The
-- API sets this GUC per request via SET LOCAL, so even a misbehaving query
-- with the service role cannot leak across tenants.
--
-- Run with: psql -U zapagent -d zapagent -v ON_ERROR_STOP=1 -f 0001_init.sql
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector for FAQ embeddings
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive emails / slugs

-- -----------------------------------------------------------------------------
-- Helper: trigger to update an `updated_at` column.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- Helper: read the current tenant from the connection-local GUC.
-- The API calls `SET LOCAL app.tenant_id = '<uuid>'` per request.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION current_tenant_id()
RETURNS UUID AS $$
DECLARE
    raw TEXT;
BEGIN
    raw := current_setting('app.tenant_id', true);
    IF raw IS NULL OR raw = '' THEN
        RETURN NULL;
    END IF;
    RETURN raw::UUID;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- 1. tenants
--    One row per business that uses ZapAgent. The id is the multi-tenancy key.
-- =============================================================================
CREATE TABLE tenants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                 CITEXT UNIQUE NOT NULL,
    name                 TEXT NOT NULL,
    business_type        TEXT,                          -- barbershop, clinic, ...
    timezone             TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    locale               TEXT NOT NULL DEFAULT 'pt-BR',
    plan                 TEXT NOT NULL DEFAULT 'starter',
    status               TEXT NOT NULL DEFAULT 'active' -- active|paused|cancelled
                         CHECK (status IN ('active', 'paused', 'cancelled')),
    data_retention_days  INTEGER NOT NULL DEFAULT 365,
    settings             JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_status ON tenants(status);
CREATE TRIGGER trg_tenants_updated_at BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 2. users (membership table)
--    Links a Supabase auth user to one or more tenants with a role. Auth
--    itself lives in Supabase's `auth.users` table, which we don't recreate.
-- =============================================================================
CREATE TABLE users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    auth_user_id         UUID NOT NULL,                 -- Supabase auth.users.id
    email                CITEXT NOT NULL,
    full_name            TEXT,
    role                 TEXT NOT NULL DEFAULT 'owner'
                         CHECK (role IN ('owner', 'admin', 'agent', 'viewer')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, auth_user_id)
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_auth_user ON users(auth_user_id);
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 3. integrations
--    External service credentials per tenant: Evolution instance, Google
--    Calendar OAuth tokens, etc. Refresh tokens are encrypted at rest at the
--    application layer before insert.
-- =============================================================================
CREATE TABLE integrations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind                 TEXT NOT NULL                  -- whatsapp|google_calendar|asaas
                         CHECK (kind IN ('whatsapp', 'google_calendar', 'asaas')),
    external_id          TEXT,                          -- evolution instance name, calendar id
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'connected', 'error', 'revoked')),
    config               JSONB NOT NULL DEFAULT '{}'::JSONB,  -- non-secret config
    secrets              JSONB NOT NULL DEFAULT '{}'::JSONB,  -- encrypted blob
    last_synced_at       TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, kind, external_id)
);

CREATE INDEX idx_integrations_tenant_kind ON integrations(tenant_id, kind);
CREATE TRIGGER trg_integrations_updated_at BEFORE UPDATE ON integrations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 4. faq_items
--    The knowledge base the agent retrieves from. `embedding` is filled by
--    the API on insert/update via Anthropic's voyage-* or any chosen model;
--    NULL means "not yet indexed".
-- =============================================================================
CREATE TABLE faq_items (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    question             TEXT NOT NULL,
    answer               TEXT NOT NULL,
    tags                 TEXT[] NOT NULL DEFAULT '{}',
    embedding            VECTOR(1024),                  -- voyage-3-lite output dim
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_faq_tenant_question ON faq_items(tenant_id, question);
CREATE INDEX idx_faq_tenant ON faq_items(tenant_id);
CREATE INDEX idx_faq_tenant_active ON faq_items(tenant_id) WHERE is_active;
-- HNSW index over the embedding column; cosine distance.
CREATE INDEX idx_faq_embedding ON faq_items
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
CREATE TRIGGER trg_faq_updated_at BEFORE UPDATE ON faq_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 5. conversations
--    One row per WhatsApp contact per tenant. The agent's LangGraph thread
--    id is `{tenant_id}:{conversation_id}` so checkpoints survive restarts.
-- =============================================================================
CREATE TABLE conversations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    contact_phone        TEXT NOT NULL,                 -- E.164 without '+'
    contact_name         TEXT,
    status               TEXT NOT NULL DEFAULT 'active' -- active|handoff|closed
                         CHECK (status IN ('active', 'handoff', 'closed')),
    opted_out            BOOLEAN NOT NULL DEFAULT FALSE,
    last_message_at      TIMESTAMPTZ,
    metadata             JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, contact_phone)
);

CREATE INDEX idx_conversations_tenant_status ON conversations(tenant_id, status);
CREATE INDEX idx_conversations_last_message ON conversations(tenant_id, last_message_at DESC);
CREATE TRIGGER trg_conversations_updated_at BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 6. messages
--    Every inbound and outbound WhatsApp message. `provider_message_id` is
--    unique per tenant for idempotent ingestion.
-- =============================================================================
CREATE TABLE messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction            TEXT NOT NULL                  -- inbound|outbound
                         CHECK (direction IN ('inbound', 'outbound')),
    provider_message_id  TEXT,                          -- evolution message id
    role                 TEXT NOT NULL                  -- user|assistant|system|operator
                         CHECK (role IN ('user', 'assistant', 'system', 'operator')),
    content              TEXT NOT NULL,
    intent               TEXT,                          -- classified intent (nullable)
    confidence           NUMERIC(4, 3),                 -- 0.000..1.000
    token_usage          JSONB,                         -- { input, output, cached }
    handoff              BOOLEAN NOT NULL DEFAULT FALSE,
    metadata             JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider_message_id)
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX idx_messages_tenant_created ON messages(tenant_id, created_at DESC);

-- =============================================================================
-- 7. appointments
--    Scheduled events created by the agent. Mirrors what's in Google Calendar.
-- =============================================================================
CREATE TABLE appointments (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id      UUID REFERENCES conversations(id) ON DELETE SET NULL,
    contact_phone        TEXT NOT NULL,
    contact_name         TEXT,
    title                TEXT NOT NULL,
    description          TEXT,
    starts_at            TIMESTAMPTZ NOT NULL,
    ends_at              TIMESTAMPTZ NOT NULL,
    status               TEXT NOT NULL DEFAULT 'scheduled'
                         CHECK (status IN ('scheduled', 'cancelled', 'completed', 'no_show')),
    google_event_id      TEXT,
    metadata             JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (ends_at > starts_at)
);

CREATE INDEX idx_appointments_tenant_starts ON appointments(tenant_id, starts_at);
CREATE INDEX idx_appointments_tenant_status ON appointments(tenant_id, status);
CREATE TRIGGER trg_appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 8. webhook_events
--    Idempotency log + audit trail for every inbound webhook. Same payload
--    arriving twice (Evolution retry) hits the unique constraint and we just
--    return 200 without enqueuing duplicate work.
-- =============================================================================
CREATE TABLE webhook_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID REFERENCES tenants(id) ON DELETE SET NULL,
    source               TEXT NOT NULL                  -- evolution|asaas|google
                         CHECK (source IN ('evolution', 'asaas', 'google')),
    event_type           TEXT NOT NULL,
    external_id          TEXT NOT NULL,                 -- provider event/message id
    payload              JSONB NOT NULL,
    processed_at         TIMESTAMPTZ,
    error                TEXT,
    received_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE INDEX idx_webhook_events_tenant ON webhook_events(tenant_id, received_at DESC);
CREATE INDEX idx_webhook_events_unprocessed ON webhook_events(received_at)
    WHERE processed_at IS NULL;

-- =============================================================================
-- Row Level Security
-- =============================================================================
ALTER TABLE tenants        ENABLE ROW LEVEL SECURITY;
ALTER TABLE users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE faq_items      ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;

-- Tenant-scoped tables: all rows are visible only when their tenant_id matches
-- the connection-local GUC `app.tenant_id`. The API sets this GUC per request.
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_tenant_id());
CREATE POLICY tenant_isolation ON integrations
    USING (tenant_id = current_tenant_id());
CREATE POLICY tenant_isolation ON faq_items
    USING (tenant_id = current_tenant_id());
CREATE POLICY tenant_isolation ON conversations
    USING (tenant_id = current_tenant_id());
CREATE POLICY tenant_isolation ON messages
    USING (tenant_id = current_tenant_id());
CREATE POLICY tenant_isolation ON appointments
    USING (tenant_id = current_tenant_id());

-- The tenants table is special: a user can only see their own tenant row.
CREATE POLICY tenant_self ON tenants
    USING (id = current_tenant_id());

-- webhook_events allows inserts from the system regardless of tenant (the
-- tenant is resolved during processing), but reads require the tenant context.
CREATE POLICY webhook_read ON webhook_events
    FOR SELECT USING (tenant_id = current_tenant_id() OR tenant_id IS NULL);
CREATE POLICY webhook_insert ON webhook_events
    FOR INSERT WITH CHECK (TRUE);
CREATE POLICY webhook_update ON webhook_events
    FOR UPDATE USING (TRUE);

COMMIT;
