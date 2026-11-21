-- Desk UPI QR collections: the customer pays HFG's Razorpay account by scanning a
-- single-use QR at the cafe desk. The bill is paid once Razorpay reports a captured
-- payment; the cafe's share stays "pending" until HFG settles it to the cafe.
CREATE TABLE IF NOT EXISTS desk_upi_collections (
 id uuid PRIMARY KEY,
 vendor_id integer NOT NULL REFERENCES vendors(id),
 booking_id integer NOT NULL,
 transaction_ids integer[] NOT NULL,
 waive_off_amount numeric(12,2) NOT NULL DEFAULT 0 CHECK (waive_off_amount >= 0),
 amount_paise integer NOT NULL CHECK (amount_paise > 0),
 qr_id text UNIQUE,
 image_url text,
 -- creating -> open -> paid | expired | closed | failed | paid_unapplied
 status text NOT NULL DEFAULT 'creating',
 payment_id text UNIQUE,
 paid_at timestamptz,
 close_by timestamptz NOT NULL,
 -- not_applicable until paid; then pending until HFG pays the cafe (settled), or review
 cafe_settlement_status text NOT NULL DEFAULT 'not_applicable',
 cafe_settled_at timestamptz,
 source_channel text NOT NULL DEFAULT 'dashboard',
 staff_id text,
 staff_name text,
 staff_role text,
 error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- At most one live QR per booking, so two staff screens cannot collect twice.
CREATE UNIQUE INDEX IF NOT EXISTS desk_upi_one_open_per_booking
 ON desk_upi_collections(booking_id) WHERE status IN ('creating','open');
CREATE INDEX IF NOT EXISTS desk_upi_cafe_settlement
 ON desk_upi_collections(vendor_id, cafe_settlement_status, paid_at);
