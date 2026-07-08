-- 0004_force_rls.sql
-- ZAP-005: defense-in-depth for multi-tenant isolation.
--
-- 0001 ENABLEs row level security but never FORCEs it. ENABLE does not apply to
-- the table owner, and the API/worker currently connect as the owning role
-- (postgres.*), so RLS is bypassed on that path and isolation rests entirely on
-- the application WHERE tenant_id filters.
--
-- FORCE ROW LEVEL SECURITY makes the policies apply to the table owner too. It
-- still does NOT apply to superuser / BYPASSRLS roles, so the complete fix is to
-- ALSO connect with a dedicated non-owner application role (see the template at
-- the bottom of this file, which is intentionally left as a documented manual
-- step because it requires a real password and a DATABASE_URL change).

ALTER TABLE tenants        FORCE ROW LEVEL SECURITY;
ALTER TABLE users          FORCE ROW LEVEL SECURITY;
ALTER TABLE integrations   FORCE ROW LEVEL SECURITY;
ALTER TABLE faq_items      FORCE ROW LEVEL SECURITY;
ALTER TABLE conversations  FORCE ROW LEVEL SECURITY;
ALTER TABLE messages       FORCE ROW LEVEL SECURITY;
ALTER TABLE appointments   FORCE ROW LEVEL SECURITY;
ALTER TABLE webhook_events FORCE ROW LEVEL SECURITY;

-- MANUAL FOLLOW-UP (run once, out of band, with a strong generated password):
--
--   CREATE ROLE encaixe_app LOGIN PASSWORD '<strong-random>' NOBYPASSRLS;
--   GRANT USAGE ON SCHEMA public TO encaixe_app;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO encaixe_app;
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO encaixe_app;
--
-- Then point DATABASE_URL / DATABASE_URL_SYNC at encaixe_app (not the owner).
-- With a non-owner role, the FORCE above makes a query that forgets its
-- tenant filter return zero rows instead of leaking across tenants.
