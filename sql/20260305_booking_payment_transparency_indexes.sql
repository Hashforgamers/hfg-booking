BEGIN;

-- Fast booking-level payment summary aggregation.
CREATE INDEX IF NOT EXISTS ix_transactions_booking_id
    ON transactions (booking_id);

CREATE INDEX IF NOT EXISTS ix_transactions_booking_settlement
    ON transactions (booking_id, settlement_status);

-- Fast lookup for active booking resolution in /extraBooking.
CREATE INDEX IF NOT EXISTS ix_bookings_slot_game_user_status
    ON bookings (slot_id, game_id, user_id, status);

COMMIT;
