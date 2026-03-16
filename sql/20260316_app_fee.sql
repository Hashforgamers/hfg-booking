-- Track platform app fee for transparency
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS app_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
