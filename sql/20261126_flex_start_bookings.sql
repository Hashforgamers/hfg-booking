-- Flex-start ("any minute") bookings. Shared booking/dashboard database.
-- Purely additive and safe to run more than once:
--   * new nullable booking columns (NULL = legacy slot booking, nothing backfilled);
--   * a new per-cafe settings table (no row = flex turned off).
-- Prerequisite: sql/20261002_shared_slot_reservations.sql from hfg-dashboard
-- (cafe_slot_reservations). Flex holds reuse that table with session_id 'flex:<booking_id>'.
-- Apply before deploying the hfg-booking / hfg-dashboard flex branches; the code
-- refuses flex requests (and leaves every slot flow unchanged) until it is applied.
BEGIN;

ALTER TABLE bookings ADD COLUMN IF NOT EXISTS start_at timestamptz;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS end_at timestamptz;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duration_minutes integer;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS timing_mode varchar(10);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bookings_timing_mode_check') THEN
    ALTER TABLE bookings ADD CONSTRAINT bookings_timing_mode_check
      CHECK (timing_mode IS NULL OR timing_mode IN ('slot', 'flex')) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bookings_flex_window_check') THEN
    ALTER TABLE bookings ADD CONSTRAINT bookings_flex_window_check
      CHECK (timing_mode IS DISTINCT FROM 'flex'
             OR (start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at AND duration_minutes > 0)) NOT VALID;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_bookings_flex_window
  ON bookings (start_at, end_at) WHERE timing_mode = 'flex';

CREATE TABLE IF NOT EXISTS vendor_flex_booking_settings (
  vendor_id integer PRIMARY KEY REFERENCES vendors(id) ON DELETE CASCADE,
  flex_enabled boolean NOT NULL DEFAULT false,
  min_minutes integer NOT NULL DEFAULT 30 CHECK (min_minutes BETWEEN 5 AND 720),
  step_minutes integer NOT NULL DEFAULT 15 CHECK (step_minutes BETWEEN 1 AND 60),
  late_arrival_policy varchar(20) NOT NULL DEFAULT 'keep_end'
    CHECK (late_arrival_policy IN ('keep_end', 'shift_if_free')),
  allow_past_closing boolean NOT NULL DEFAULT false,
  partial_slot_grace_minutes integer NOT NULL DEFAULT 0 CHECK (partial_slot_grace_minutes BETWEEN 0 AND 30),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Flex holds are looked up per booking.
CREATE INDEX IF NOT EXISTS ix_cafe_slot_reservations_session
  ON cafe_slot_reservations (session_id) WHERE released_at IS NULL;

COMMIT;

-- Rollback (only if no flex booking was ever created):
-- BEGIN;
-- DROP TABLE IF EXISTS vendor_flex_booking_settings;
-- DROP INDEX IF EXISTS ix_bookings_flex_window;
-- ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_flex_window_check;
-- ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_timing_mode_check;
-- ALTER TABLE bookings DROP COLUMN IF EXISTS timing_mode, DROP COLUMN IF EXISTS duration_minutes,
--   DROP COLUMN IF EXISTS end_at, DROP COLUMN IF EXISTS start_at;
-- COMMIT;
