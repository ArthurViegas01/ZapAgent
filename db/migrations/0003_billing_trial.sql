-- =============================================================================
-- 0003 — Trial window + subscription status on tenants.
--
-- Lightweight billing primitives that let the agent stop replying to a
-- paying customer's WhatsApp when their subscription lapses, BEFORE the
-- full Asaas integration (P2) lands. The pilot will use manual Pix
-- payments + an operator marking subscription_status='active' by hand;
-- the table shape is forward-compatible with an Asaas webhook handler.
--
-- Idempotent: every statement uses IF NOT EXISTS / ON CONFLICT semantics
-- so re-running on a partially-migrated DB is safe.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------
-- 1. Columns
-- -----------------------------------------------------------------------
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'trialing',
    ADD COLUMN IF NOT EXISTS trial_ends_at       TIMESTAMPTZ;

-- CHECK is added separately so it can fail loudly if old rows somehow
-- hold an unsupported value (defaults guarantee they don't).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'tenants_subscription_status_check'
    ) THEN
        ALTER TABLE tenants
            ADD CONSTRAINT tenants_subscription_status_check
            CHECK (subscription_status IN ('trialing', 'active', 'past_due', 'suspended'));
    END IF;
END$$;

-- -----------------------------------------------------------------------
-- 2. Backfill: every existing tenant gets a 14-day trial starting now.
--    Already-set rows are left untouched (idempotency).
-- -----------------------------------------------------------------------
UPDATE tenants
   SET trial_ends_at = NOW() + INTERVAL '14 days'
 WHERE trial_ends_at IS NULL
   AND subscription_status = 'trialing';

-- -----------------------------------------------------------------------
-- 3. Index for the billing gate's hot-path lookup.
--    The webhook handler reads (subscription_status, trial_ends_at) per
--    tenant on every inbound message; partial index keeps it tiny.
-- -----------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tenants_subscription
    ON tenants (subscription_status, trial_ends_at);

COMMIT;
