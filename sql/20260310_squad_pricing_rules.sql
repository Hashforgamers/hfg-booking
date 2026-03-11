BEGIN;

CREATE TABLE IF NOT EXISTS squad_pricing_rules (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    console_group VARCHAR(20) NOT NULL,
    player_count INTEGER NOT NULL,
    discount_percent NUMERIC(6,2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_squad_rule_vendor_group_players UNIQUE (vendor_id, console_group, player_count)
);

CREATE INDEX IF NOT EXISTS ix_squad_pricing_rules_vendor_group
    ON squad_pricing_rules (vendor_id, console_group, is_active, player_count);

COMMIT;
