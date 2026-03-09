BEGIN;

-- Speed up /api/vendor/<vendor_id>/passes/available
CREATE INDEX IF NOT EXISTS ix_cafe_passes_vendor_active_mode_price
    ON cafe_passes (vendor_id, is_active, pass_mode, price);
CREATE INDEX IF NOT EXISTS ix_cafe_passes_global_active_mode_price
    ON cafe_passes (is_active, pass_mode, price)
    WHERE vendor_id IS NULL;

-- Speed up /api/games/vendor/<vendor_id>
CREATE INDEX IF NOT EXISTS ix_opening_days_vendor_open_day
    ON opening_days (vendor_id, is_open, day);

-- Speed up /api/getSlots/vendor/<vendor_id>/game/<game_id>/<date>
CREATE INDEX IF NOT EXISTS ix_transactions_vendor_booked_date_booking
    ON transactions (vendor_id, booked_date, booking_id);
CREATE INDEX IF NOT EXISTS ix_bookings_game_slot_status
    ON bookings (game_id, slot_id, status);
CREATE INDEX IF NOT EXISTS ix_slots_gaming_type_time
    ON slots (gaming_type_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS ix_available_game_console_console_game
    ON available_game_console (console_id, available_game_id);

-- Ensure all dynamic vendor slot tables can filter fast by date + slot_id.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'vendor\_%\_slot' ESCAPE '\\'
    LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (date, slot_id);',
            t.tablename || '_date_slot_idx',
            t.tablename
        );
    END LOOP;
END $$;

COMMIT;
