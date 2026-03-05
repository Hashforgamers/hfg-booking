BEGIN;

-- Speed up filters/join used by /api/getSlotsBatch/vendor/<vendor_id>.
CREATE INDEX IF NOT EXISTS ix_slots_gaming_type_id_start_time
    ON slots (gaming_type_id, start_time);

CREATE INDEX IF NOT EXISTS ix_available_games_vendor_id_id
    ON available_games (vendor_id, id);

-- Add the same (date, slot_id) composite index to every dynamic vendor slot table.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'vendor\_%\_slot' ESCAPE '\'
    LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (date, slot_id);',
            t.tablename || '_date_slot_idx',
            t.tablename
        );
    END LOOP;
END $$;

COMMIT;
