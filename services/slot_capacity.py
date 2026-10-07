"""Dated capacity contract shared by independently deployed booking services.

The caller owns the transaction: capacity and its booking/claim commit together.
"""
from sqlalchemy import text


def reserve_slot(session, vendor_id, slot_id, day, units=1):
    if type(units) is not int or units < 1:
        raise ValueError('Slot units must be a positive integer')
    row = session.execute(text(f'''UPDATE VENDOR_{int(vendor_id)}_SLOT
        SET available_slot=available_slot-:units,
            is_available=(available_slot-:units > 0)
        WHERE vendor_id=:vendor AND slot_id=:slot AND date=:day
          AND is_available=true AND available_slot>=:units
        RETURNING available_slot'''),
        {'vendor':int(vendor_id), 'slot':int(slot_id), 'day':day, 'units':units}).first()
    if row is None:
        raise ValueError('Slot is no longer available. Refresh and choose another slot.')
    return row[0]


def release_slot(session, vendor_id, slot_id, day, units=1):
    if type(units) is int and units == 0:
        row=session.execute(text(f'SELECT available_slot FROM VENDOR_{int(vendor_id)}_SLOT WHERE vendor_id=:vendor AND slot_id=:slot AND date=:day'),
            {'vendor':int(vendor_id),'slot':int(slot_id),'day':day}).first()
        if row is None: raise ValueError('Slot schedule is missing')
        return row[0]
    if type(units) is not int or units < 1:
        raise ValueError('Slot units must be a positive integer')
    row = session.execute(text(f'''UPDATE VENDOR_{int(vendor_id)}_SLOT
        SET available_slot=available_slot+:units, is_available=true
        WHERE vendor_id=:vendor AND slot_id=:slot AND date=:day
        RETURNING available_slot'''),
        {'vendor':int(vendor_id), 'slot':int(slot_id), 'day':day, 'units':units}).first()
    if row is None:
        raise ValueError('Slot schedule is missing; capacity was not released.')
    return row[0]


def booking_units(details):
    """Use persisted units rather than reinterpreting mutable console settings."""
    details = details if isinstance(details, dict) else {}
    if details.get('remaining_slot_units') is not None:
        return max(0,int(details['remaining_slot_units']))
    stored = details.get('slot_units')
    if stored is not None:
        return max(1, int(stored))
    players = max(1, int(details.get('player_count') or details.get('playerCount') or 1))
    return players if details.get('console_group') == 'pc' and (details.get('enabled') or players > 1) else 1
