-- Shared booking/dashboard database. Apply before enabling console-linked desk booking.
BEGIN;
CREATE OR REPLACE FUNCTION desk_guard_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected jsonb; cid integer; conflict boolean; starts timestamp; finishes timestamp;
BEGIN
 IF NEW.book_status NOT IN ('current','upcoming') THEN RETURN NEW; END IF;
 SELECT squad_details::jsonb->'desk_console_ids' INTO expected FROM bookings WHERE id=NEW.book_id;
 IF expected IS NOT NULL AND jsonb_array_length(expected)>0 THEN
   IF NEW.console_id IS NULL OR NOT expected @> to_jsonb(NEW.console_id) THEN
     RAISE EXCEPTION 'Use the console reserved for this rate card' USING ERRCODE='23514';
   END IF;
 ELSE
   expected := CASE WHEN NEW.console_id>0 THEN jsonb_build_array(NEW.console_id) ELSE '[]'::jsonb END;
 END IF;
 starts := NEW.date+NEW.start_time; finishes := NEW.date+NEW.end_time;
 IF finishes<=starts THEN finishes:=finishes+interval '1 day'; END IF;
 FOR cid IN SELECT value::integer FROM jsonb_array_elements_text(expected) ORDER BY value::integer LOOP
   PERFORM id FROM consoles WHERE id=cid FOR UPDATE;
   EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I d LEFT JOIN bookings b ON b.id=d.book_id
     WHERE d.book_id IS DISTINCT FROM $1 AND d.book_status IN (''upcoming'',''current'')
       AND (d.console_id=$2 OR COALESCE(b.squad_details::jsonb->''assigned_console_ids'',''[]''::jsonb) @> to_jsonb($2))
       AND d.date+d.start_time<$4 AND $3<d.date+d.end_time+
         CASE WHEN d.end_time<=d.start_time THEN interval ''1 day'' ELSE interval ''0 day'' END)',TG_TABLE_NAME)
       INTO conflict USING NEW.book_id,cid,starts,finishes;
   IF conflict THEN RAISE EXCEPTION 'Console reserved for another session' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
DO $$ DECLARE t record; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename ~ '^vendor_[0-9]+_dashboard$' LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS desk_assignment_guard ON %I',t.tablename);
   EXECUTE format('CREATE TRIGGER desk_assignment_guard BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION desk_guard_assignment()',t.tablename);
 END LOOP;
END $$;
COMMIT;
