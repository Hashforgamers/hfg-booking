-- Phase 1: Global console catalog + vendor overrides (backward compatible)

CREATE TABLE IF NOT EXISTS console_catalog (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(80) NOT NULL UNIQUE,
    display_name VARCHAR(120) NOT NULL,
    family VARCHAR(80) NOT NULL DEFAULT 'other',
    icon VARCHAR(64) NULL,
    input_mode VARCHAR(32) NOT NULL DEFAULT 'controller',
    supports_multiplayer BOOLEAN NOT NULL DEFAULT FALSE,
    default_capacity INTEGER NOT NULL DEFAULT 1,
    controller_policy VARCHAR(32) NOT NULL DEFAULT 'none',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendor_console_overrides (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    console_catalog_id INTEGER NULL REFERENCES console_catalog(id) ON DELETE SET NULL,
    slug VARCHAR(80) NULL,
    display_name VARCHAR(120) NULL,
    family VARCHAR(80) NULL,
    icon VARCHAR(64) NULL,
    input_mode VARCHAR(32) NULL,
    supports_multiplayer BOOLEAN NULL,
    default_capacity INTEGER NULL,
    controller_policy VARCHAR(32) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vendor_console_override_slug UNIQUE (vendor_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_vendor_console_overrides_vendor
    ON vendor_console_overrides(vendor_id);

INSERT INTO console_catalog
    (slug, display_name, family, icon, input_mode, supports_multiplayer, default_capacity, controller_policy, is_active)
VALUES
    ('pc', 'PC', 'computer', 'Monitor', 'keyboard_mouse', TRUE, 10, 'none', TRUE),
    ('playstation', 'PlayStation', 'console', 'Tv', 'controller', TRUE, 4, 'per_player', TRUE),
    ('xbox', 'Xbox', 'console', 'Gamepad2', 'controller', TRUE, 4, 'per_player', TRUE),
    ('vr_headset', 'VR Headset', 'immersive', 'Headset', 'motion', FALSE, 1, 'none', TRUE),
    ('nintendo_switch', 'Nintendo Switch', 'console', 'Gamepad2', 'controller', TRUE, 4, 'per_player', TRUE),
    ('steam_deck', 'Steam Deck', 'handheld', 'Gamepad2', 'hybrid', TRUE, 2, 'optional', TRUE),
    ('arcade_cabinet', 'Arcade Cabinet', 'arcade', 'Gamepad2', 'joystick', TRUE, 2, 'none', TRUE),
    ('racing_rig', 'Racing Rig', 'simulator', 'Joystick', 'wheel', FALSE, 1, 'none', TRUE),
    ('simulator', 'Simulator', 'simulator', 'Rocket', 'specialized', FALSE, 1, 'none', TRUE),
    ('private_room', 'Private Room', 'zone', 'DoorOpen', 'room', TRUE, 8, 'none', TRUE),
    ('vip_room', 'VIP Room', 'zone', 'Crown', 'room', TRUE, 10, 'none', TRUE),
    ('bootcamp_room', 'Bootcamp Room', 'zone', 'Users', 'room', TRUE, 12, 'none', TRUE)
ON CONFLICT (slug) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    family = EXCLUDED.family,
    icon = EXCLUDED.icon,
    input_mode = EXCLUDED.input_mode,
    supports_multiplayer = EXCLUDED.supports_multiplayer,
    default_capacity = EXCLUDED.default_capacity,
    controller_policy = EXCLUDED.controller_policy,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();
