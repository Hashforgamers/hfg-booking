BEGIN;
-- Historical receipts can identify a player by name without a HASH user account.
ALTER TABLE transactions ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_import_player;
ALTER TABLE transactions ADD CONSTRAINT transactions_import_player
    CHECK (user_id IS NOT NULL OR (source_channel IS NOT DISTINCT FROM 'excel_import' AND booking_id IS NULL));
CREATE UNIQUE INDEX IF NOT EXISTS transactions_import_source_key
    ON transactions(vendor_id, reference_id) WHERE source_channel = 'excel_import';
COMMIT;
