-- Per-cafe policy for paid time left unused when a desk session ends early.
-- Purely additive and safe to run more than once. No row = default policy
-- ('credit_default': cafe wallet credit, staff may refund cash instead; 5 min minimum).
-- The code works without this table (everyone gets the default); the table is
-- only needed to let a cafe change the setting in Settings > Session Timing.
BEGIN;

CREATE TABLE IF NOT EXISTS vendor_unused_time_settings (
  vendor_id integer PRIMARY KEY REFERENCES vendors(id) ON DELETE CASCADE,
  policy varchar(20) NOT NULL DEFAULT 'credit_default'
    CHECK (policy IN ('credit_default', 'credit', 'refund', 'none')),
  min_unused_minutes integer NOT NULL DEFAULT 5 CHECK (min_unused_minutes BETWEEN 0 AND 60),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Returns are looked up by booking (negative early_release_* transactions).
CREATE INDEX IF NOT EXISTS ix_transactions_early_release
  ON transactions (booking_id) WHERE booking_type IN ('early_release_credit', 'early_release_refund');

COMMIT;

-- Rollback:
-- BEGIN; DROP INDEX IF EXISTS ix_transactions_early_release; DROP TABLE IF EXISTS vendor_unused_time_settings; COMMIT;
