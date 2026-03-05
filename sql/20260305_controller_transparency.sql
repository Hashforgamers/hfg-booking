BEGIN;

-- 1) Controller pricing configuration
CREATE TABLE IF NOT EXISTS controller_pricing_rules (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    available_game_id INTEGER NOT NULL REFERENCES available_games(id) ON DELETE CASCADE,
    base_price NUMERIC(10,2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_controller_rule_vendor_game UNIQUE (vendor_id, available_game_id)
);

CREATE INDEX IF NOT EXISTS ix_controller_pricing_rules_vendor_id ON controller_pricing_rules(vendor_id);
CREATE INDEX IF NOT EXISTS ix_controller_pricing_rules_available_game_id ON controller_pricing_rules(available_game_id);
CREATE INDEX IF NOT EXISTS ix_controller_pricing_rules_is_active ON controller_pricing_rules(is_active);

CREATE TABLE IF NOT EXISTS controller_pricing_tiers (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES controller_pricing_rules(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL,
    total_price NUMERIC(10,2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_controller_tier_rule_quantity UNIQUE (rule_id, quantity),
    CONSTRAINT check_controller_tier_quantity_gte_2 CHECK (quantity >= 2),
    CONSTRAINT check_controller_tier_total_price_gte_0 CHECK (total_price >= 0)
);

CREATE INDEX IF NOT EXISTS ix_controller_pricing_tiers_rule_id ON controller_pricing_tiers(rule_id);
CREATE INDEX IF NOT EXISTS ix_controller_pricing_tiers_is_active ON controller_pricing_tiers(is_active);

-- 2) Vendor GST profile
CREATE TABLE IF NOT EXISTS vendor_tax_profiles (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    gst_registered BOOLEAN NOT NULL DEFAULT FALSE,
    gstin VARCHAR(20),
    legal_name VARCHAR(255),
    state_code VARCHAR(2),
    place_of_supply_state_code VARCHAR(2),
    gst_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    gst_rate DOUBLE PRECISION NOT NULL DEFAULT 18,
    tax_inclusive BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vendor_tax_profile_vendor UNIQUE (vendor_id)
);

CREATE INDEX IF NOT EXISTS ix_vendor_tax_profiles_vendor_id ON vendor_tax_profiles(vendor_id);

-- 3) Transaction transparency columns
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS payment_use_case VARCHAR(100);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source_channel VARCHAR(20) NOT NULL DEFAULT 'app';
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS initiated_by_staff_id VARCHAR(100);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS initiated_by_staff_name VARCHAR(255);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS initiated_by_staff_role VARCHAR(50);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS base_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS meals_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS controller_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS waive_off_amount DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS taxable_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS gst_rate DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS cgst_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS sgst_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS igst_amount DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS total_with_tax DOUBLE PRECISION NOT NULL DEFAULT 0;

-- 4) Time wallet (unused/remaining slot minutes)
CREATE TABLE IF NOT EXISTS time_wallet_accounts (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    balance_minutes INTEGER NOT NULL DEFAULT 0,
    balance_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_time_wallet_vendor_user UNIQUE (vendor_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_time_wallet_accounts_vendor_id ON time_wallet_accounts(vendor_id);
CREATE INDEX IF NOT EXISTS ix_time_wallet_accounts_user_id ON time_wallet_accounts(user_id);

CREATE TABLE IF NOT EXISTS time_wallet_ledgers (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES time_wallet_accounts(id) ON DELETE CASCADE,
    booking_id INTEGER REFERENCES bookings(id),
    transaction_id INTEGER REFERENCES transactions(id),
    entry_type VARCHAR(30) NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 0,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    description VARCHAR(255),
    source_channel VARCHAR(20) NOT NULL DEFAULT 'app',
    staff_id VARCHAR(100),
    staff_name VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_time_wallet_ledgers_account_id ON time_wallet_ledgers(account_id);
CREATE INDEX IF NOT EXISTS ix_time_wallet_ledgers_booking_id ON time_wallet_ledgers(booking_id);
CREATE INDEX IF NOT EXISTS ix_time_wallet_ledgers_transaction_id ON time_wallet_ledgers(transaction_id);

-- 5) Monthly credit (play now, settle month-end)
CREATE TABLE IF NOT EXISTS monthly_credit_accounts (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credit_limit DOUBLE PRECISION NOT NULL DEFAULT 0,
    outstanding_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    billing_cycle_day INTEGER NOT NULL DEFAULT 1,
    grace_days INTEGER NOT NULL DEFAULT 5,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_monthly_credit_vendor_user UNIQUE (vendor_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_monthly_credit_accounts_vendor_id ON monthly_credit_accounts(vendor_id);
CREATE INDEX IF NOT EXISTS ix_monthly_credit_accounts_user_id ON monthly_credit_accounts(user_id);

ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS customer_name VARCHAR(255);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(20);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(255);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS state VARCHAR(100);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS pincode VARCHAR(20);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS id_proof_type VARCHAR(50);
ALTER TABLE monthly_credit_accounts ADD COLUMN IF NOT EXISTS id_proof_number VARCHAR(100);

CREATE TABLE IF NOT EXISTS monthly_credit_ledgers (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES monthly_credit_accounts(id) ON DELETE CASCADE,
    transaction_id INTEGER REFERENCES transactions(id),
    entry_type VARCHAR(30) NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    description VARCHAR(255),
    booked_date DATE,
    due_date DATE,
    source_channel VARCHAR(20) NOT NULL DEFAULT 'app',
    staff_id VARCHAR(100),
    staff_name VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_monthly_credit_ledgers_account_id ON monthly_credit_ledgers(account_id);
CREATE INDEX IF NOT EXISTS ix_monthly_credit_ledgers_transaction_id ON monthly_credit_ledgers(transaction_id);

COMMIT;
