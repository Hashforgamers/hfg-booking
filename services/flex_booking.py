"""Database side of flex-start bookings. Rules live in services.flex_timing.

Capacity model (unchanged for slot bookings):
- the booking row's slot_id/booked date is the "base" slot, reserved by
  BookingService.create_booking exactly like a slot booking;
- every other dated slot the window overlaps is reserved through the shared
  slot_capacity contract and recorded in cafe_slot_reservations under
  session_id ``flex:<booking_id>``. The availability endpoints already count
  those rows, so their leak-repair never hands the units back early.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db.extensions import db
from services import flex_timing as ft
from services.flex_timing import FlexError

HOLD_PREFIX = "flex:"
_schema_ready = False


def hold_key(booking_id):
    return f"{HOLD_PREFIX}{int(booking_id)}"


def schema_ready(force=False):
    """True once the 20261126 migration (and the shared reservations table) exist."""
    global _schema_ready
    if _schema_ready and not force:
        return True
    row = db.session.execute(text("""SELECT
        (SELECT count(*) FROM information_schema.columns
          WHERE table_schema=current_schema() AND table_name='bookings'
            AND column_name IN ('start_at','end_at','duration_minutes','timing_mode')),
        to_regclass('vendor_flex_booking_settings') IS NOT NULL,
        to_regclass('cafe_slot_reservations') IS NOT NULL""")).first()
    _schema_ready = bool(row and int(row[0]) == 4 and row[1] and row[2])
    return _schema_ready


def require_schema():
    if not schema_ready():
        raise FlexError("Flex start times need the 20261126_flex_start_bookings migration on the booking database.",
                        503, "migration_required")


def load_settings(vendor_id):
    settings = dict(ft.DEFAULT_SETTINGS)
    if not schema_ready():
        return settings
    row = db.session.execute(text("""SELECT flex_enabled,min_minutes,step_minutes,late_arrival_policy,
        allow_past_closing,partial_slot_grace_minutes FROM vendor_flex_booking_settings WHERE vendor_id=:v"""),
        {"v": int(vendor_id)}).mappings().first()
    if row:
        settings.update({k: row[k] for k in ft.DEFAULT_SETTINGS if row[k] is not None})
    return settings


def save_settings(vendor_id, payload):
    require_schema()
    merged = ft.normalize_settings(payload, load_settings(vendor_id))
    db.session.execute(text("""INSERT INTO vendor_flex_booking_settings
        (vendor_id,flex_enabled,min_minutes,step_minutes,late_arrival_policy,allow_past_closing,partial_slot_grace_minutes,updated_at)
        VALUES(:vendor_id,:flex_enabled,:min_minutes,:step_minutes,:late_arrival_policy,:allow_past_closing,:partial_slot_grace_minutes,now())
        ON CONFLICT(vendor_id) DO UPDATE SET flex_enabled=excluded.flex_enabled,min_minutes=excluded.min_minutes,
          step_minutes=excluded.step_minutes,late_arrival_policy=excluded.late_arrival_policy,
          allow_past_closing=excluded.allow_past_closing,partial_slot_grace_minutes=excluded.partial_slot_grace_minutes,
          updated_at=now()"""), dict(merged, vendor_id=int(vendor_id)))
    return merged


def require_enabled(vendor_id):
    require_schema()
    settings = load_settings(vendor_id)
    if not settings["flex_enabled"]:
        raise FlexError("Custom start times are turned off for this cafe. Turn them on in Settings > Session Timing.",
                        403, "flex_disabled")
    return settings


def dedupe(occurrences):
    """Duplicate logical slots (same dated window) keep the row with more room, like the slot grid does."""
    best = {}
    for item in occurrences:
        key = (item.start, item.end)
        current = best.get(key)
        if current is None or (item.available, item.is_available) > (current.available, current.is_available):
            best[key] = item
    return sorted(best.values(), key=lambda o: (o.start, o.slot_id))


def load_occurrences(vendor_id, game_id, first_day, last_day):
    rows = db.session.execute(text(f"""SELECT v.date,v.slot_id,v.available_slot,v.is_available,s.start_time,s.end_time
        FROM VENDOR_{int(vendor_id)}_SLOT v JOIN slots s ON s.id=v.slot_id
        WHERE v.vendor_id=:v AND s.gaming_type_id=:g AND v.date BETWEEN :a AND :b
        ORDER BY v.date,v.slot_id"""), {"v": int(vendor_id), "g": int(game_id), "a": first_day, "b": last_day}).mappings()
    return dedupe([ft.occurrence(r["date"], r["slot_id"], r["start_time"], r["end_time"],
                                 r["available_slot"], r["is_available"]) for r in rows])


def lock_consumed(vendor_id, consumed, units):
    """Row-lock every consumed dated slot in (date, slot_id) order, then re-check room."""
    fresh = []
    for item in sorted(consumed, key=lambda o: (o.day, o.slot_id)):
        row = db.session.execute(text(f"""SELECT available_slot,is_available FROM VENDOR_{int(vendor_id)}_SLOT
            WHERE vendor_id=:v AND date=:d AND slot_id=:s FOR UPDATE"""),
            {"v": int(vendor_id), "d": item.day, "s": item.slot_id}).first()
        if row is None or not row[1] or int(row[0] or 0) < units:
            raise FlexError(f"The {ft.clock(item.start)} slot just filled up. Refresh and choose another time.",
                            409, "slot_full", slot_id=item.slot_id, date=item.day.isoformat())
        fresh.append(item)
    return fresh


def game_consoles(vendor_id, game_id):
    rows = db.session.execute(text("""SELECT c.id,c.model_number AS name,c.console_number FROM consoles c
        JOIN available_game_console a ON a.console_id=c.id
        WHERE c.vendor_id=:v AND a.available_game_id=:g
          AND NOT EXISTS (SELECT 1 FROM maintenance_status m WHERE m.console_id=c.id
                          AND lower(m.available_status) LIKE '%maintenance%')
        ORDER BY c.id"""), {"v": int(vendor_id), "g": int(game_id)}).mappings()
    return [dict(r) for r in rows]


def _ids(value):
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except ValueError:
            return set()
    if not isinstance(value, list):
        return set()
    return {int(x) for x in value if str(x).lstrip("-").isdigit()}


def console_busy(vendor_id, console_ids, start, end, now, exclude_booking_ids=()):
    """Busy intervals per console from dashboard rows (slot or flex windows) and QR claims."""
    wanted = {int(c) for c in console_ids}
    busy = {cid: [] for cid in wanted}
    if not wanted:
        return busy
    rows = db.session.execute(text(f"""SELECT d.book_id,d.console_id,d.book_status,d.date,d.start_time,d.end_time,
            b.squad_details
        FROM VENDOR_{int(vendor_id)}_DASHBOARD d LEFT JOIN bookings b ON b.id=d.book_id
        WHERE d.book_status IN ('current','upcoming')
          AND (d.book_status='current' OR d.date BETWEEN :a AND :b)"""),
        {"a": start.date() - timedelta(days=1), "b": end.date()}).mappings().all()
    excluded = {int(b) for b in exclude_booking_ids}
    for row in rows:
        if row["book_id"] is not None and int(row["book_id"]) in excluded:
            continue
        if row["date"] is None or row["start_time"] is None or row["end_time"] is None:
            continue
        details = row["squad_details"] if isinstance(row["squad_details"], dict) else {}
        holders = ({int(row["console_id"])} if row["console_id"] and int(row["console_id"]) > 0 else set())
        holders |= _ids(details.get("assigned_console_ids")) - _ids(details.get("released_console_ids"))
        for interval in ft.busy_intervals([row], now):
            for cid in holders & wanted:
                busy[cid].append(interval)
    if db.session.execute(text("SELECT to_regclass('cafe_play_sessions') IS NOT NULL")).scalar():
        claims = db.session.execute(text("""SELECT console_claim,
              ((COALESCE(started_at,created_at) AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata') AS left_edge,
              ((COALESCE(ends_at,booking_end,deadline+minutes*interval '1 minute') AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata') AS right_edge
            FROM cafe_play_sessions WHERE console_claim=ANY(:ids)"""), {"ids": sorted(wanted)}).mappings()
        for claim in claims:
            left, right = claim["left_edge"], claim["right_edge"]
            if left is None:
                continue
            right = max(right or now, ft.overtime_end(now))
            busy[int(claim["console_claim"])].append((left, right))
    return {cid: sorted(items) for cid, items in busy.items()}


def lock_consoles(vendor_id, console_ids):
    # Same lock the desk console guard and QR claims take, in id order.
    db.session.execute(text("SELECT id FROM consoles WHERE vendor_id=:v AND id=ANY(:ids) ORDER BY id FOR UPDATE"),
                       {"v": int(vendor_id), "ids": sorted(int(c) for c in console_ids)}).all()


def plan_window(vendor_id, game_id, start, minutes, settings, units=1, now=None):
    now = now or datetime.now(ft.IST).replace(tzinfo=None)
    occurrences = load_occurrences(vendor_id, game_id, start.date() - timedelta(days=1),
                                   (start + timedelta(minutes=max(minutes, ft.MAX_MINUTES))).date() + timedelta(days=1))
    plan = ft.build_plan(occurrences, start, minutes, settings, units, now)
    return plan, occurrences


def stations(vendor_id, game_id, plan, now, exclude_booking_ids=(), consoles=None):
    consoles = consoles if consoles is not None else game_consoles(vendor_id, game_id)
    busy = console_busy(vendor_id, [c["id"] for c in consoles], plan.start, plan.end, now, exclude_booking_ids)
    return ft.evaluate_consoles(consoles, busy, plan)


def pick_consoles(vendor_id, game_id, plan, quantity, requested=None, now=None, exclude_booking_ids=()):
    """Lock and choose ``quantity`` stations free for the whole window."""
    now = now or datetime.now(ft.IST).replace(tzinfo=None)
    consoles = game_consoles(vendor_id, game_id)
    if not consoles:
        raise FlexError("No working stations are linked to this device type.", 409, "no_station")
    lock_consoles(vendor_id, [c["id"] for c in consoles])
    evaluated = stations(vendor_id, game_id, plan, now, exclude_booking_ids, consoles)
    free = [s["console_id"] for s in evaluated if s["available"]]
    if requested:
        ids = [int(c) for c in requested]
        if len(ids) != quantity or len(set(ids)) != quantity or any(c not in free for c in ids):
            raise FlexError("The chosen station is busy during this window. Refresh and pick a free station.",
                            409, "station_busy", stations=evaluated)
        return ids, evaluated
    if len(free) < quantity:
        best = max((s["max_minutes_available"] for s in evaluated), default=0)
        raise FlexError("No station is free for the whole window.", 409, "station_busy",
                        stations=evaluated, max_minutes=best)
    return free[:quantity], evaluated


def hold_extra(vendor_id, booking_id, occurrences, units):
    """Reserve non-base overlapped slots and record them for release/repair accounting."""
    from services.slot_capacity import reserve_slot
    for item in sorted(occurrences, key=lambda o: (o.day, o.slot_id)):
        reserve_slot(db.session, vendor_id, item.slot_id, item.day, units)
        db.session.execute(text("""INSERT INTO cafe_slot_reservations(session_id,vendor_id,date,slot_id,units)
            VALUES(:sid,:v,:d,:s,:u)
            ON CONFLICT(session_id,vendor_id,date,slot_id) DO UPDATE SET units=excluded.units, released_at=NULL"""),
            {"sid": hold_key(booking_id), "v": int(vendor_id), "d": item.day, "s": item.slot_id, "u": int(units)})


def held(vendor_id, booking_id):
    if not schema_ready():
        return []
    rows = db.session.execute(text("""SELECT date,slot_id,units FROM cafe_slot_reservations
        WHERE session_id=:sid AND vendor_id=:v AND released_at IS NULL ORDER BY date,slot_id"""),
        {"sid": hold_key(booking_id), "v": int(vendor_id)}).mappings()
    return [dict(r) for r in rows]


def release_holds(vendor_id, booking_id, keys=None):
    """Return a flex booking's extra slot units. Safe to call for any booking (no rows -> no-op)."""
    if not vendor_id or not booking_id or not schema_ready():
        return 0
    from services.slot_capacity import release_slot
    rows = db.session.execute(text("""SELECT date,slot_id,units FROM cafe_slot_reservations
        WHERE session_id=:sid AND vendor_id=:v AND released_at IS NULL
        ORDER BY date,slot_id FOR UPDATE"""), {"sid": hold_key(booking_id), "v": int(vendor_id)}).mappings().all()
    released = 0
    for row in rows:
        if keys is not None and (row["date"], int(row["slot_id"])) not in keys:
            continue
        release_slot(db.session, vendor_id, row["slot_id"], row["date"], int(row["units"]))
        db.session.execute(text("""UPDATE cafe_slot_reservations SET released_at=:now
            WHERE session_id=:sid AND vendor_id=:v AND date=:d AND slot_id=:s"""),
            {"now": datetime.now(timezone.utc).replace(tzinfo=None), "sid": hold_key(booking_id),
             "v": int(vendor_id), "d": row["date"], "s": row["slot_id"]})
        released += 1
    return released


def write_timing(booking_id, start, end):
    db.session.execute(text("""UPDATE bookings SET start_at=:s,end_at=:e,duration_minutes=:m,timing_mode='flex'
        WHERE id=:id"""), {"s": start.replace(tzinfo=ft.IST), "e": end.replace(tzinfo=ft.IST),
                           "m": ft.minutes_between(start, end), "id": int(booking_id)})


def timing_for(booking_ids):
    """{booking_id: {...}} for flex bookings; empty before the migration."""
    ids = sorted({int(b) for b in booking_ids if b})
    if not ids or not schema_ready():
        return {}
    rows = db.session.execute(text("""SELECT id,start_at,end_at,duration_minutes,timing_mode FROM bookings
        WHERE id=ANY(:ids) AND timing_mode='flex'"""), {"ids": ids}).mappings()
    result = {}
    for r in rows:
        start = r["start_at"].astimezone(ft.IST).replace(tzinfo=None) if r["start_at"] else None
        end = r["end_at"].astimezone(ft.IST).replace(tzinfo=None) if r["end_at"] else None
        result[int(r["id"])] = {"timing_mode": "flex", "start_at": ft.iso(start), "end_at": ft.iso(end),
                                "duration_minutes": r["duration_minutes"]}
    return result
