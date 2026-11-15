CREATE TABLE IF NOT EXISTS whatsapp_outbox (
 id uuid PRIMARY KEY, vendor_id integer NOT NULL REFERENCES vendors(id),
 recipient varchar(15) NOT NULL, template text NOT NULL, language text NOT NULL,
 parameters jsonb NOT NULL, consent_note text NOT NULL, actor text NOT NULL,
 status text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
 provider_id text UNIQUE, error text, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(), next_attempt timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS whatsapp_queue ON whatsapp_outbox(status,next_attempt);
CREATE INDEX IF NOT EXISTS whatsapp_vendor_history ON whatsapp_outbox(vendor_id,created_at DESC);
CREATE TABLE IF NOT EXISTS whatsapp_optouts (recipient varchar(15) PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS whatsapp_config (id integer PRIMARY KEY CHECK(id=1), values_encrypted text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS whatsapp_wallet (vendor_id integer PRIMARY KEY REFERENCES vendors(id), credits integer NOT NULL DEFAULT 0 CHECK(credits>=0));
CREATE TABLE IF NOT EXISTS whatsapp_purchases (
 id uuid PRIMARY KEY, vendor_id integer NOT NULL REFERENCES vendors(id), amount_paise integer NOT NULL CHECK(amount_paise>0),
 credits integer NOT NULL DEFAULT 100 CHECK(credits=100), order_id text UNIQUE, payment_id text UNIQUE,
 status text NOT NULL DEFAULT 'pending', created_at timestamptz NOT NULL DEFAULT now(), paid_at timestamptz
);
CREATE TABLE IF NOT EXISTS whatsapp_credit_ledger (
 id bigserial PRIMARY KEY, vendor_id integer NOT NULL REFERENCES vendors(id), delta integer NOT NULL,
 reference text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS whatsapp_cafe_settings (
 vendor_id integer PRIMARY KEY REFERENCES vendors(id), preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
 enabled_since timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS whatsapp_contacts (
 vendor_id integer NOT NULL REFERENCES vendors(id), recipient varchar(15) NOT NULL,
 service_consent boolean NOT NULL DEFAULT false, marketing_consent boolean NOT NULL DEFAULT false,
 consent_note text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(vendor_id,recipient)
);
ALTER TABLE whatsapp_outbox ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'updates';
ALTER TABLE whatsapp_outbox ADD COLUMN IF NOT EXISTS expires_at timestamptz;
