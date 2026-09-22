BEGIN;
CREATE TABLE IF NOT EXISTS cafe_login_challenges (
 id varchar(36) PRIMARY KEY,
 user_id integer,
 email_hash varchar(64) NOT NULL,
 ip_hash varchar(64) NOT NULL,
 code_hash varchar(64) NOT NULL,
 attempts integer NOT NULL DEFAULT 0,
 created_at timestamp NOT NULL,
 expires_at timestamp NOT NULL,
 consumed_at timestamp
);
CREATE INDEX IF NOT EXISTS ix_cafe_login_email ON cafe_login_challenges(email_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_cafe_login_ip ON cafe_login_challenges(ip_hash, created_at);
COMMIT;
