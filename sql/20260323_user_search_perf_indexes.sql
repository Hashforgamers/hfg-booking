-- Speed up vendor-scoped user typeahead lookups used by dashboard booking form.
CREATE INDEX IF NOT EXISTS idx_transactions_vendor_user_created_at
ON transactions (vendor_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_users_name_lower
ON users ((lower(name)));

CREATE INDEX IF NOT EXISTS idx_contact_info_phone_lower
ON contact_info ((lower(phone)))
WHERE parent_type = 'user';

CREATE INDEX IF NOT EXISTS idx_contact_info_email_lower
ON contact_info ((lower(email)))
WHERE parent_type = 'user';

