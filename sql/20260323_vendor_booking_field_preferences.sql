-- Vendor booking form field preferences for dashboard booking UX.
CREATE TABLE IF NOT EXISTS vendor_booking_field_preferences (
    vendor_id INTEGER PRIMARY KEY REFERENCES vendors(id) ON DELETE CASCADE,
    require_name BOOLEAN NOT NULL DEFAULT TRUE,
    show_phone BOOLEAN NOT NULL DEFAULT TRUE,
    require_phone BOOLEAN NOT NULL DEFAULT TRUE,
    show_email BOOLEAN NOT NULL DEFAULT TRUE,
    require_email BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

