-- =============================================================================
-- 0002 - Fix RLS policies for Next.js / Supabase JS client
--
-- Problem: all tenant_isolation policies require the app.tenant_id GUC to be
-- set via "SET LOCAL app.tenant_id = ...". The Supabase JS client never does
-- this, so queries from Next.js server components always return 0 rows.
--
-- Fix: add secondary policy conditions that use auth.uid() so the JS client
-- can read rows it owns without needing the GUC.
-- =============================================================================

-- Create auth schema stub for local Postgres. Supabase provides
-- auth.uid() natively in production; we MUST NOT overwrite it there.
-- The DO block runs the CREATE OR REPLACE only when the function does
-- not already exist — under Supabase, this is a no-op.
CREATE SCHEMA IF NOT EXISTS auth;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'auth' AND p.proname = 'uid'
    ) THEN
        EXECUTE $func$
            CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $body$
                SELECT NULL::uuid
            $body$
        $func$;
    END IF;
END$$;

BEGIN;

-- -----------------------------------------------------------------------
-- tenants: allow users to read tenants they belong to
-- -----------------------------------------------------------------------
DROP POLICY IF EXISTS tenant_isolation ON tenants;
CREATE POLICY tenant_read ON tenants
    FOR SELECT USING (
        id = current_tenant_id()          -- API path (GUC set)
        OR id IN (                        -- JS client path (JWT uid)
            SELECT tenant_id FROM users
            WHERE auth_user_id = auth.uid()
        )
    );
CREATE POLICY tenant_write ON tenants
    FOR ALL USING (id = current_tenant_id());

-- -----------------------------------------------------------------------
-- users: allow members to read their own memberships
-- -----------------------------------------------------------------------
DROP POLICY IF EXISTS tenant_isolation ON users;
CREATE POLICY user_read ON users
    FOR SELECT USING (
        tenant_id = current_tenant_id()   -- API path
        OR auth_user_id = auth.uid()      -- JS client: own rows
    );
CREATE POLICY user_write ON users
    FOR ALL USING (tenant_id = current_tenant_id());

-- -----------------------------------------------------------------------
-- Other tables: keep GUC-only isolation (accessed via API, not JS client)
-- integrations, faq_items, conversations, messages, appointments
-- already have tenant_isolation policies — leave them unchanged.
-- -----------------------------------------------------------------------

COMMIT;
