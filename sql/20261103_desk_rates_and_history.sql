BEGIN;
DO $$
BEGIN
    IF to_regclass('vendors') IS NULL OR to_regclass('available_games') IS NULL
       OR to_regclass('cafe_passes') IS NULL THEN
        RAISE EXCEPTION 'Booking tables are missing or not visible in database % (search_path: %).',
            current_database(), current_setting('search_path')
            USING HINT = 'Select the database and schema used by hfg-booking before running this migration.';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS desk_rate_cards (
    vendor_id integer NOT NULL REFERENCES vendors(id),
    game_id integer NOT NULL REFERENCES available_games(id),
    profile varchar(40) NOT NULL,
    rates jsonb NOT NULL,
    PRIMARY KEY(vendor_id, game_id, profile)
);
CREATE TABLE IF NOT EXISTS desk_booking_archive (
    vendor_id integer NOT NULL REFERENCES vendors(id),
    source_key varchar(100) NOT NULL,
    player varchar(150) NOT NULL,
    device varchar(100) NOT NULL,
    played_on date NOT NULL,
    started time NOT NULL,
    ended time NOT NULL,
    paid numeric(12,2) NOT NULL CHECK(paid >= 0),
    PRIMARY KEY(vendor_id, source_key)
);
CREATE INDEX IF NOT EXISTS desk_archive_date_idx ON desk_booking_archive(vendor_id, played_on DESC, source_key);

ALTER TABLE cafe_passes ADD COLUMN IF NOT EXISTS pc_only boolean NOT NULL DEFAULT false;

COMMIT;
