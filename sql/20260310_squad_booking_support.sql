BEGIN;

ALTER TABLE bookings
    ADD COLUMN IF NOT EXISTS squad_details JSONB;

CREATE TABLE IF NOT EXISTS booking_squad_members (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    member_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    member_position INTEGER NOT NULL,
    is_captain BOOLEAN NOT NULL DEFAULT FALSE,
    name_snapshot VARCHAR(255) NOT NULL,
    phone_snapshot VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_booking_squad_members_booking_id
    ON booking_squad_members (booking_id);
CREATE INDEX IF NOT EXISTS ix_booking_squad_members_member_user_id
    ON booking_squad_members (member_user_id);
CREATE INDEX IF NOT EXISTS ix_booking_squad_members_phone_snapshot
    ON booking_squad_members (phone_snapshot);

COMMIT;
