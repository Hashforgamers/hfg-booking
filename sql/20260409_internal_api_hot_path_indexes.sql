-- Internal API hot-path indexes for booking read endpoints.
-- Safe to run multiple times.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_bookings_user_created_desc
    ON bookings (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bookings_user_status_booked_date_desc
    ON bookings (user_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_available_games_vendor_id_id
    ON available_games (vendor_id, id);

CREATE INDEX IF NOT EXISTS idx_console_pricing_offers_lookup_window
    ON console_pricing_offers (
        vendor_id,
        available_game_id,
        is_active,
        start_date,
        end_date,
        start_time,
        end_time,
        offered_price
    );

CREATE INDEX IF NOT EXISTS idx_controller_pricing_rules_vendor_game_active
    ON controller_pricing_rules (vendor_id, available_game_id, is_active);

CREATE INDEX IF NOT EXISTS idx_squad_pricing_rules_vendor_console_active
    ON squad_pricing_rules (vendor_id, console_group, is_active);

COMMIT;
