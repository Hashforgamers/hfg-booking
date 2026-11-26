-- Walk-in gamers (e.g. kids) may have only a name: allow contact_info rows
-- without a phone or email. Missing values are stored as NULL, never ''.
-- Safe to run more than once. Existing rows are untouched.
ALTER TABLE contact_info ALTER COLUMN phone DROP NOT NULL;
ALTER TABLE contact_info ALTER COLUMN email DROP NOT NULL;

-- Optional clean-up of fake values written by older desk-booking code.
-- Review the counts first; run the UPDATEs only once the columns are nullable.
-- SELECT count(*) FROM contact_info WHERE parent_type = 'user' AND phone = '0000000000';
-- SELECT count(*) FROM contact_info WHERE parent_type = 'user' AND email LIKE 'noemail\_%@hash.local';
-- UPDATE contact_info SET phone = NULL WHERE parent_type = 'user' AND (phone = '0000000000' OR phone LIKE 'nophone-%');
-- UPDATE contact_info SET email = NULL WHERE parent_type = 'user' AND email LIKE 'noemail\_%@hash.local';
