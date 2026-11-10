"""Physical console compatibility and full-window reservation for desk rates."""
from datetime import datetime, timedelta
from sqlalchemy import text
from db.extensions import db


def consoles(vendor, game):
    return [dict(row) for row in db.session.execute(text('''SELECT c.id,c.model_number AS name,
        max(h.screen_size_inches) AS screen_size_inches FROM consoles c
        JOIN available_game_console a ON a.console_id=c.id
        LEFT JOIN hardware_specifications h ON h.console_id=c.id
        WHERE c.vendor_id=:v AND a.available_game_id=:g GROUP BY c.id,c.model_number ORDER BY c.id'''),dict(v=vendor,g=game)).mappings()]


def validate_mapping(vendor, game, definition):
    ids=definition.get('console_ids',[])
    allowed={row['id']:row for row in consoles(vendor,game)}
    for cid in ids:
        if cid not in allowed:
            raise ValueError('Choose consoles belonging to this cafe and device type.')
        if definition.get('screen_size_inches') and allowed[cid]['screen_size_inches'] != definition['screen_size_inches']:
            raise ValueError('Linked consoles must match the rate card TV size. Update Console Management first.')


def windows(day, slots):
    result=[]
    for slot in slots:
        start=datetime.combine(day,slot.start_time);end=datetime.combine(day,slot.end_time)
        if end<=start:end+=timedelta(days=1)
        result.append((start,end))
    if not result:raise ValueError('Choose session times.')
    return result


def available(vendor, game, definition, spans, lock=False):
    validate_mapping(vendor,game,definition)
    mapped=set(definition.get('console_ids',[]))
    if not mapped:raise ValueError('Link physical consoles to this rate card in Console Pricing before booking.')
    if lock:
        # Serialize assignments in a consistent order through the existing console guards.
        db.session.execute(text('SELECT id FROM consoles WHERE vendor_id=:v AND id=ANY(:ids) ORDER BY id FOR UPDATE'),dict(v=vendor,ids=sorted(mapped))).all()
    result=[]
    for row in consoles(vendor,game):
        cid=row['id']
        if cid not in mapped:continue
        if db.session.execute(text("SELECT 1 FROM maintenance_status WHERE console_id=:c AND lower(available_status) LIKE '%maintenance%'"),dict(c=cid)).first():continue
        conflict=False
        for start,end in spans:
            conflict=db.session.execute(text(f'''SELECT 1 FROM VENDOR_{int(vendor)}_DASHBOARD d
                LEFT JOIN bookings b ON b.id=d.book_id
                WHERE d.book_status IN ('current','upcoming')
                  AND (d.console_id=:c OR COALESCE(b.squad_details::jsonb->'assigned_console_ids','[]'::jsonb) @> to_jsonb(CAST(:c AS integer)))
                  AND (d.book_status='current' OR (d.date+d.start_time<:end AND :start<d.date+d.end_time+
                    CASE WHEN d.end_time<=d.start_time THEN interval '1 day' ELSE interval '0 day' END)) LIMIT 1'''),dict(c=cid,start=start,end=end)).first()
            if conflict:break
            # QR/kiosk claims share the same physical devices.
            conflict=db.session.execute(text('''SELECT 1 FROM cafe_play_sessions WHERE console_claim=:c
                AND :start < ((COALESCE(ends_at,booking_end,deadline+minutes*interval '1 minute') AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')
                AND ((COALESCE(started_at,created_at) AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata') < :end LIMIT 1'''),dict(c=cid,start=start,end=end)).first()
            if conflict:break
        if not conflict:result.append(row)
    return result


def reserve(vendor,game,definition,spans,quantity,requested=None):
    guard=db.session.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:table) AND tgname='desk_assignment_guard' AND tgenabled<>'D'"),dict(table=f"vendor_{int(vendor)}_dashboard")).first()
    if not guard:raise ValueError("Apply the console-assignment migration for this cafe before booking linked consoles.")
    rows=available(vendor,game,definition,spans,lock=True)
    candidates={row['id'] for row in rows}
    ids=requested if requested else [row['id'] for row in rows[:quantity]]
    if not isinstance(ids,list) or len(ids)!=quantity or len(set(ids))!=quantity or any(type(cid) is not int or cid not in candidates for cid in ids):
        raise ValueError('The selected consoles are unavailable or incompatible. Refresh and choose available consoles.')
    return ids
