"""Cap scheduled capacity by physical consoles still held by live bookings."""
from datetime import datetime, timedelta
from sqlalchemy import text
from db.extensions import db


def load_console_holds(vendor_id, game_ids):
    # Current rows deliberately have no date/end cutoff: checkout releases the hold.
    # Include squad assignments and deduplicate physical consoles, not booking rows.
    rows = db.session.execute(text(f"""
        SELECT DISTINCT a.available_game_id, c.id AS console_id,
            d.book_status, d.date, d.start_time, d.end_time
        FROM consoles c
        JOIN available_game_console a ON a.console_id=c.id
        LEFT JOIN (vendor_{int(vendor_id)}_dashboard d
            LEFT JOIN bookings b ON b.id=d.book_id)
          ON d.book_status IN ('current','upcoming') AND
            (d.console_id=c.id OR
             COALESCE(b.squad_details::jsonb->'assigned_console_ids','[]'::jsonb)
                 @> to_jsonb(c.id))
        WHERE c.vendor_id=:vendor AND a.available_game_id=ANY(:games)
    """), {"vendor": vendor_id, "games": list(game_ids)}).mappings()
    result = {}
    for row in rows:
        result.setdefault(row['available_game_id'], {}).setdefault(row['console_id'], []).append(dict(row))
    return result


def free_console_capacity(holds, game_id, day, start_time, end_time):
    if isinstance(day, str):
        day = datetime.strptime(day, '%Y-%m-%d').date()
    start = datetime.combine(day, start_time)
    end = datetime.combine(day, end_time)
    if end <= start:
        end += timedelta(days=1)
    free = 0
    for bookings in holds.get(game_id, {}).values():
        occupied = False
        for booking in bookings:
            if booking['book_status'] == 'current':
                occupied = True
                break
            if booking['book_status'] != 'upcoming':
                continue
            reserved_start = datetime.combine(booking['date'], booking['start_time'])
            reserved_end = datetime.combine(booking['date'], booking['end_time'])
            if reserved_end <= reserved_start:
                reserved_end += timedelta(days=1)
            if start < reserved_end and reserved_start < end:
                occupied = True
                break
        if not occupied:
            free += 1
    return free
