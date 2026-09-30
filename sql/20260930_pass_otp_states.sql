BEGIN;
CREATE TABLE IF NOT EXISTS pass_otp_states (
    key varchar(64) PRIMARY KEY,
    kind varchar(20) NOT NULL,
    payload json NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pass_otp_states_kind ON pass_otp_states(kind);
COMMIT;
