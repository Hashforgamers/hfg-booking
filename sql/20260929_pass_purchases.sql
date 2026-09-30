BEGIN;
CREATE TABLE IF NOT EXISTS pass_purchases (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key VARCHAR(100) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    user_pass_id INTEGER NOT NULL REFERENCES user_passes(id),
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_pass_purchase_request UNIQUE (user_id, idempotency_key)
);
COMMIT;
