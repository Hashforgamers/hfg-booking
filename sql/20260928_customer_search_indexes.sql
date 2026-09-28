-- Run outside a transaction; CONCURRENTLY keeps customer/booking writes available.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_search_vendor_user
    ON transactions (vendor_id, user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_search_name_prefix
    ON users (lower(name) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_search_phone_prefix
    ON contact_info (lower(phone) text_pattern_ops) WHERE parent_type = 'user';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_search_email_prefix
    ON contact_info (lower(email) text_pattern_ops) WHERE parent_type = 'user';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_search_contact_user
    ON contact_info (parent_id) WHERE parent_type = 'user';
