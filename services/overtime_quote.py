"""Server-side overtime pricing for desk check out.

The dashboard used to work out overtime from the browser clock and send the
amount. The server now prices it from the booking's own slot chain, so the
charge does not depend on which device or clock the desk uses.
"""
import math
from datetime import datetime, timedelta

import pytz
from sqlalchemy.sql import text

IST = pytz.timezone("Asia/Kolkata")

# "slot": overtime costs the booked slot price per slot length (same rate as
# the booking). "hour": the slot price is charged per hour (the old rule).
RATE_BASIS = "slot"

# Past this much overtime the desk must say when play really ended, so a
# session nobody checked out cannot quietly bill days of play.
STALE_OVERTIME_SECONDS = 3 * 3600


class OvertimeError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def ist_now():
    return datetime.now(IST).replace(tzinfo=None)


def _span(day, start, end):
    begin = datetime.combine(day, start)
    finish = datetime.combine(day, end)
    if finish <= begin:
        finish += timedelta(days=1)
    return begin, finish


def rate_per_hour(slot_price, slot_seconds, basis=None):
    basis = basis or RATE_BASIS
    price = float(slot_price or 0)
    if basis == "hour" or not slot_seconds:
        return price
    return price * 3600.0 / float(slot_seconds)


def price_overtime(overtime_seconds, hourly_rate):
    """Same rounding the desk always used: whole rupees, rounded up."""
    if overtime_seconds <= 0 or hourly_rate <= 0:
        return 0.0
    return float(math.ceil(overtime_seconds / 3600.0 * hourly_rate))


def chain_end(rows, booking_id):
    """End of the run of back-to-back slots that contains this booking.

    rows: dicts with book_id, date, start_time, end_time for one gamer on one
    console. Consecutive bookings are merged on the dashboard, so overtime
    only starts after the last of them.
    """
    spans = sorted((_span(r["date"], r["start_time"], r["end_time"]) + (int(r["book_id"]),) for r in rows),
                   key=lambda s: s[0])
    own = [s for s in spans if s[2] == int(booking_id)]
    if not own:
        return None
    end = max(s[1] for s in own)
    changed = True
    while changed:
        changed = False
        for begin, finish, _ in spans:
            if begin <= end < finish or begin == end:
                if finish > end:
                    end = finish
                    changed = True
    return end


def quote(session, vendor_id, booking, console_id=None, played_until=None, now=None):
    from models.availableGame import AvailableGame
    from models.slot import Slot

    vendor_id = int(vendor_id)
    now = now or ist_now()
    table = f"VENDOR_{vendor_id}_DASHBOARD"
    own = session.execute(text(f"""SELECT book_id,user_id,console_id,date,start_time,end_time,book_status
        FROM {table} WHERE book_id=:bid ORDER BY start_time"""), {"bid": booking.id}).mappings().all()
    if console_id is not None:
        own = [r for r in own if r["console_id"] is None or str(r["console_id"]) == str(console_id)] or own
    if not own:
        raise OvertimeError("Booking is not on this cafe's dashboard", 404)
    first = own[0]
    rows = session.execute(text(f"""SELECT book_id,date,start_time,end_time FROM {table}
        WHERE user_id=:uid AND date BETWEEN :day AND :next_day
          AND (CAST(:cid AS integer) IS NULL OR console_id=:cid)
          AND book_status IN ('current','upcoming','extra','completed')"""),
        {"uid": first["user_id"], "day": first["date"], "next_day": first["date"] + timedelta(days=1),
         "cid": first["console_id"]}).mappings().all()
    rows = list(rows) + [dict(r) for r in own]
    end = chain_end(rows, booking.id)

    game = AvailableGame.query.filter_by(id=booking.game_id, vendor_id=vendor_id).first()
    slot = Slot.query.filter_by(id=booking.slot_id).first()
    if not game or not slot:
        raise OvertimeError("Booking price could not be found", 409)
    begin, finish = _span(first["date"], slot.start_time, slot.end_time)
    hourly = rate_per_hour(game.single_slot_price, (finish - begin).total_seconds())

    overtime_until = now
    if played_until is not None:
        if played_until > now + timedelta(minutes=1):
            raise OvertimeError("Play cannot end in the future")
        overtime_until = max(end, played_until)
    seconds = max(0, int((overtime_until - end).total_seconds()))

    recorded = float(session.execute(text("""SELECT COALESCE(SUM(COALESCE(base_amount,amount)),0)
        FROM transactions WHERE booking_id=:bid AND booking_type='extra'
          AND COALESCE(settlement_status,'') NOT IN ('cancelled','canceled','refunded','reversed')"""),
        {"bid": booking.id}).scalar() or 0)
    gross = price_overtime(seconds, hourly)
    return {
        "booking_id": booking.id,
        "scheduled_end": end.isoformat(),
        "priced_until": overtime_until.isoformat(),
        "overtime_seconds": seconds,
        "rate_per_hour": round(hourly, 2),
        "rate_basis": RATE_BASIS,
        "gross_amount": gross,
        "already_recorded": round(recorded, 2),
        "amount": max(0.0, round(gross - recorded, 2)),
        "needs_end_time": played_until is None and seconds > STALE_OVERTIME_SECONDS,
        "stale_after_seconds": STALE_OVERTIME_SECONDS,
        "server_time": now.isoformat(),
    }


def parse_played_until(value):
    """Accept an ISO time; naive values are IST, aware values are converted."""
    if value in (None, ""):
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise OvertimeError("played_until must be an ISO date-time")
    if moment.tzinfo is not None:
        moment = moment.astimezone(IST).replace(tzinfo=None)
    return moment
