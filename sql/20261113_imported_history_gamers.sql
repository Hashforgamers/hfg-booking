-- Run after 20261108_backfill_imported_history.sql.
BEGIN;

CREATE OR REPLACE FUNCTION link_imported_history_gamers(cafe_id integer, source_keys text[])
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    -- The history archive only identifies players by name. Scope the identity
    -- to the cafe and keep it separate from existing account identities.
    INSERT INTO users (fid, name, game_username, parent_type, platform)
    SELECT DISTINCT ON (identity) identity, user_name, identity, 'user', 'app'
    FROM (
        SELECT user_name, 'excel_' || md5(vendor_id::text || ':' ||
            lower(regexp_replace(btrim(user_name), '[[:space:]]+', ' ', 'g'))) AS identity
        FROM transactions
        WHERE source_channel = 'excel_import' AND booking_type = 'historical_session'
          AND (cafe_id IS NULL OR vendor_id = cafe_id)
          AND (source_keys IS NULL OR reference_id = ANY(source_keys))
          AND btrim(user_name) <> ''
    ) AS players
    ORDER BY identity, user_name
    ON CONFLICT (fid) DO NOTHING;

    UPDATE transactions AS receipt
    SET user_id = gamer.id
    FROM users AS gamer
    WHERE receipt.source_channel = 'excel_import' AND receipt.booking_type = 'historical_session'
      AND (cafe_id IS NULL OR receipt.vendor_id = cafe_id)
      AND (source_keys IS NULL OR receipt.reference_id = ANY(source_keys))
      AND gamer.fid = 'excel_' || md5(receipt.vendor_id::text || ':' ||
          lower(regexp_replace(btrim(receipt.user_name), '[[:space:]]+', ' ', 'g')))
      AND receipt.user_id IS DISTINCT FROM gamer.id;
END;
$$;

SELECT link_imported_history_gamers(NULL, NULL);

COMMIT;
