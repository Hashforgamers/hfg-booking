"""Atomic schedule changes for upcoming bookings; financial records stay intact."""
from datetime import datetime, timedelta
import json
from sqlalchemy import text


def move_slot(session, vendor_id, booking_id, target_slot_id, target_date, now):
    vendor_id = int(vendor_id)
    session.execute(text('SELECT id FROM bookings WHERE id=:id FOR UPDATE'), {'id': booking_id})
    row = session.execute(text('''
        SELECT b.id, b.slot_id, b.game_id, b.status, b.squad_details, g.game_name,
               s.start_time, s.end_time, MIN(t.booked_date) AS booked_date
        FROM bookings b JOIN available_games g ON g.id=b.game_id
        JOIN slots s ON s.id=b.slot_id JOIN transactions t ON t.booking_id=b.id
        WHERE b.id=:booking_id AND g.vendor_id=:vendor_id
        GROUP BY b.id, g.game_name, s.start_time, s.end_time
    '''), {'booking_id': booking_id, 'vendor_id': vendor_id}).mappings().first()
    if not row:
        raise ValueError('Booking not found.')
    # Serialize edits with check-in/cancellation and re-read status under lock.
    dashboard_status = session.execute(text(f'SELECT book_status FROM VENDOR_{vendor_id}_DASHBOARD WHERE book_id=:id FOR UPDATE'), {'id': booking_id}).scalar()
    if dashboard_status != 'upcoming':
        raise ValueError('Only upcoming slots can be edited. Refresh booking details.')
    status = row['status']
    if status != 'confirmed' or datetime.combine(row['booked_date'], row['start_time']) <= now:
        raise ValueError('Only upcoming, confirmed slots can be edited.')
    target = session.execute(text('SELECT start_time, end_time FROM slots WHERE id=:id AND gaming_type_id=:game'), {'id': target_slot_id, 'game': row['game_id']}).mappings().first()
    if not target or datetime.combine(target_date, target['start_time']) <= now:
        raise ValueError('Choose a future slot for the same console type.')
    def duration(start, end):
        return (datetime.combine(target_date, end) - datetime.combine(target_date, start)).total_seconds() % 86400
    if duration(row['start_time'], row['end_time']) != duration(target['start_time'], target['end_time']):
        raise ValueError('Choose a slot with the same duration. Add or remove slots to change duration.')
    if int(row['slot_id']) == target_slot_id and row['booked_date'] == target_date:
        return
    # Slot units follow the original reservation, including multi-PC squads.
    from controllers.booking_controller import _requires_multi_console_units
    squad = row['squad_details'] or {}
    from services.slot_capacity import booking_units
    units = booking_units(squad) if 'slot_units' in squad else (max(1, int(squad.get('player_count', 1))) if squad.get('enabled') and _requires_multi_console_units(row['game_name'], vendor_id) else 1)
    table = f'VENDOR_{vendor_id}_SLOT'
    session.execute(text(f"""SELECT slot_id FROM {table}
        WHERE vendor_id=:vendor AND ((slot_id=:old_slot AND date=:old_date)
          OR (slot_id=:new_slot AND date=:new_date)) ORDER BY date, slot_id FOR UPDATE"""),
        {'vendor': vendor_id, 'old_slot': row['slot_id'], 'old_date': row['booked_date'],
         'new_slot': target_slot_id, 'new_date': target_date})
    reserved = session.execute(text(f'''UPDATE {table} SET available_slot=available_slot-:units,
        is_available=(available_slot-:units > 0) WHERE slot_id=:slot AND date=:date
        AND vendor_id=:vendor AND is_available=true AND available_slot>=:units RETURNING slot_id'''),
        {'units': units, 'slot': target_slot_id, 'date': target_date, 'vendor': vendor_id}).first()
    if not reserved:
        raise ValueError('That slot is no longer available. Choose another slot.')
    released = session.execute(text(f'''UPDATE {table} SET available_slot=available_slot+:units,
        is_available=TRUE WHERE slot_id=:slot AND date=:date AND vendor_id=:vendor RETURNING slot_id'''),
        {'units': units, 'slot': row['slot_id'], 'date': row['booked_date'], 'vendor': vendor_id}).first()
    if not released:
        raise ValueError('Original slot availability is missing; the booking was not changed.')
    details = dict(squad, booked_date=target_date.isoformat(), slot_units=units)
    session.execute(text('UPDATE bookings SET slot_id=:slot, squad_details=CAST(:details AS json), updated_at=NOW() WHERE id=:id'),
        {'slot':target_slot_id, 'id':booking_id, 'details':json.dumps(details)})
    session.execute(text('UPDATE transactions SET booked_date=:date WHERE booking_id=:id'), {'date': target_date, 'id': booking_id})
    session.execute(text(f'''UPDATE VENDOR_{vendor_id}_DASHBOARD SET date=:date, start_time=:start,
        end_time=:end WHERE book_id=:id AND book_status='upcoming' '''),
        {'date': target_date, 'start': target['start_time'], 'end': target['end_time'], 'id': booking_id})
