-- Prevent one captured Razorpay payment from confirming multiple booking batches.

CREATE TABLE IF NOT EXISTS booking_gateway_payments (
    id serial PRIMARY KEY,
    payment_id varchar(120) NOT NULL UNIQUE,
    order_id varchar(120) NOT NULL UNIQUE,
    user_id integer NOT NULL,
    amount numeric(12, 2) NOT NULL CHECK (amount >= 0),
    currency varchar(8) NOT NULL DEFAULT 'INR',
    status varchar(32) NOT NULL DEFAULT 'processing',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_booking_gateway_payments_user_status
    ON booking_gateway_payments(user_id, status);
