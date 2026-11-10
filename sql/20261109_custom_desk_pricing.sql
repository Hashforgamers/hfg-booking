BEGIN;
ALTER TABLE desk_rate_cards ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;
ALTER TABLE desk_rate_cards ADD COLUMN IF NOT EXISTS definition jsonb;
ALTER TABLE desk_rate_cards ADD COLUMN IF NOT EXISTS archived boolean NOT NULL DEFAULT false;
ALTER TABLE desk_rate_cards ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
-- Legacy rows are read with a compatible definition and become fully custom on their next save.
CREATE TABLE IF NOT EXISTS desk_pricing_settings (
    vendor_id integer NOT NULL REFERENCES vendors(id),
    game_id integer NOT NULL REFERENCES available_games(id),
    mode varchar(16) NOT NULL CHECK (mode IN ('slot','variants')),
    PRIMARY KEY(vendor_id,game_id)
);
INSERT INTO desk_pricing_settings(vendor_id,game_id,mode)
SELECT vendor_id,game_id,CASE WHEN bool_or(is_active AND NOT archived) THEN 'variants' ELSE 'slot' END
FROM desk_rate_cards GROUP BY vendor_id,game_id
ON CONFLICT(vendor_id,game_id) DO NOTHING;
COMMIT;
