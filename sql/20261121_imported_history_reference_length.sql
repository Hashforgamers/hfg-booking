-- Run in the booking database before importing historical desk sessions.
-- Dashboard import keys contain a workbook SHA-256 fingerprint and row identity.
-- The application model permits 100 characters; older databases may still have
-- transactions.reference_id at VARCHAR(50), which rejects those keys.
BEGIN;

ALTER TABLE transactions
    ALTER COLUMN reference_id TYPE VARCHAR(100);

COMMIT;
