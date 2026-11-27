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


def chain_bounds(rows, booking_id):
    """(start, end, booked_seconds) of the run of back-to-back slots that
    contains this booking, or None.

    rows: dicts with book_id, date, start_time, end_time for one gamer on one
    console. Consecutive bookings are merged on the dashboard, so overtime
    only starts after the last of them, and the whole run is the booked play.
    """
    spans = sorted(set(_span(r["date"], r["start_time"], r["end_time"]) + (int(r["book_id"]),) for r in rows),
                   key=lambda s: s[0])
    own = [s for s in spans if s[2] == int(booking_id)]
    if not own:
        return None
    start = min(s[0] for s in own)
    end = max(s[1] for s in own)
    changed = True
    while changed:
        changed = False
        for begin, finish, _ in spans:
            if begin <= end < finish or begin == end:
                if finish > end:
                    end = finish
                    changed = True
            if begin < start <= finish:
                start = begin
                changed = True
    covered, cursor = 0.0, start
    for begin, finish, _ in spans:
        if finish <= start or begin >= end:
            continue
        begin, finish = max(begin, cursor), min(finish, end)
        if finish > begin:
            covered += (finish - begin).total_seconds()
            cursor = finish
    return start, end, covered


def chain_end(rows, booking_id):
    bounds = chain_bounds(rows, booking_id)
    return bounds[1] if bounds else None


def load_rate_cards(session, vendor_id, game_id):
    """(pricing_mode, cards) for this device from the desk rate-card tables."""
    mode = session.execute(text("""SELECT mode FROM desk_pricing_settings
        WHERE vendor_id=:v AND game_id=:g"""), {"v": vendor_id, "g": game_id}).scalar() or "slot"
    cards = session.execute(text("""SELECT profile,revision,definition,rates,is_active,archived
        FROM desk_rate_cards WHERE vendor_id=:v AND game_id=:g
          AND is_active=true AND archived=false ORDER BY profile"""),
        {"v": vendor_id, "g": game_id}).mappings().all()
    return mode, [dict(c) for c in cards]


def load_offers(session, vendor_id, game_id, start, end):
    """Active console offers that overlap start..end (naive IST)."""
    from types import SimpleNamespace
    try:
        rows = session.execute(text("""SELECT start_date,start_time,end_date,end_time,offered_price,is_active
            FROM console_pricing_offers WHERE vendor_id=:v AND available_game_id=:g AND is_active=true
              AND start_date <= :last AND end_date >= :first"""),
            {"v": vendor_id, "g": game_id, "first": start.date(), "last": end.date()}).mappings().all()
        return [SimpleNamespace(**dict(r)) for r in rows]
    except Exception:
        return []


def booking_players(booking):
    details = booking.squad_details if isinstance(getattr(booking, "squad_details", None), dict) else {}
    try:
        return max(1, int(details.get("player_count") or details.get("playerCount") or 1))
    except (TypeError, ValueError):
        return 1


def rate_card_price(session, vendor_id, booking, console_id, booked_seconds, own_seconds, overtime_seconds):
    """(price_in_rupees, card, players) from the cafe's rate card, or (None, None, players)."""
    from services import extra_play_pricing as epp

    players = booking_players(booking)
    details = booking.squad_details if isinstance(getattr(booking, "squad_details", None), dict) else {}
    desk = details.get("desk_pricing") if isinstance(details.get("desk_pricing"), dict) else {}
    mode, cards = load_rate_cards(session, vendor_id, booking.game_id)
    if not cards:
        return None, None, players
    physical = details.get("desk_console_ids") or details.get("assigned_console_ids") or []
    console = physical[0] if isinstance(physical, list) and len(physical) == 1 else console_id
    candidates = epp.candidate_cards(cards, pricing_mode=mode, stored_profile=desk.get("profile"),
                                     game_title=desk.get("selected_game") or "", console_id=console)
    # What the booked part actually cost, for a fixed package the card cannot
    # quote by duration. Only known when this booking is the whole run.
    paid_base = desk.get("slot_base_amount") if abs(booked_seconds - own_seconds) < 1 else None
    price, card = epp.best_extra_price(candidates, booked_seconds / 60.0, overtime_seconds / 60.0,
                                       players, paid_base)
    return (None if price is None else float(math.ceil(price))), card, players


def quote(session, vendor_id, booking, console_id=None, played_until=None, now=None, squad_multiplier=1):
    """squad_multiplier: how many times the desk multiplies a slot-rate amount
    for this squad (PC squads pay per player). A rate-card amount already
    covers the whole squad, so the desk must not multiply it again."""
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
    _start, end, booked_seconds = chain_bounds(rows, booking.id)

    game = AvailableGame.query.filter_by(id=booking.game_id, vendor_id=vendor_id).first()
    slot = Slot.query.filter_by(id=booking.slot_id).first()
    if not game or not slot:
        raise OvertimeError("Booking price could not be found", 409)
    begin, finish = _span(first["date"], slot.start_time, slot.end_time)
    own_seconds = (finish - begin).total_seconds()
    hourly = rate_per_hour(game.single_slot_price, (finish - begin).total_seconds())

    overtime_until = now
    if played_until is not None:
        if played_until > now + timedelta(minutes=1):
            raise OvertimeError("Play cannot end in the future")
        overtime_until = max(end, played_until)
    seconds = max(0, int((overtime_until - end).total_seconds()))

    # What earlier overtime lines billed for the whole squad, before any waiver
    # (a waived rupee must not be billed again at the next check out).
    recorded = float(session.execute(text("""SELECT COALESCE(SUM(COALESCE(original_amount,base_amount,amount)),0)
        FROM transactions WHERE booking_id=:bid AND booking_type='extra'
          AND COALESCE(settlement_status,'') NOT IN ('cancelled','canceled','refunded','reversed')"""),
        {"bid": booking.id}).scalar() or 0)
    offers = load_offers(session, vendor_id, booking.game_id, end, end + timedelta(seconds=seconds)) if seconds else []
    if offers:
        # An offer running during the extra time lowers it, the same lowest
        # price rule slot bookings use (IST wall clock, offer must cover the
        # minutes it discounts). Same whole-rupee round-up as before.
        from services.pricing_math import interval_amount
        slot_seconds = 3600 if (RATE_BASIS == "hour" or not own_seconds) else own_seconds
        exact = interval_amount(game.single_slot_price, offers, end, end + timedelta(seconds=seconds), slot_seconds)
        gross = float(math.ceil(exact)) if exact > 0 else 0.0
        hourly = gross * 3600.0 / seconds
    else:
        gross = price_overtime(seconds, hourly)
    multiplier = max(1, int(squad_multiplier or 1))
    card_price, card, players = rate_card_price(session, vendor_id, booking, console_id,
                                                booked_seconds, own_seconds, seconds)
    # The rate card is used only when it is no dearer than the old slot-rate
    # charge for the same play (gross x squad multiplier). This change can
    # therefore only lower what a gamer pays for extra time, never raise it.
    source = "slot_rate"
    if card_price is not None and card_price <= gross * multiplier:
        source = "rate_card"
        gross = card_price
        if seconds:
            hourly = gross * 3600.0 / seconds
    else:
        # Price the whole squad here, like the rate card does. Earlier lines in
        # `recorded` are whole-squad amounts, so subtracting them from a
        # per-player gross under-charged the next check out (PC squad of 3 at
        # Rs 60/h: 1h over with Rs 90 already billed came out as Rs 0, not
        # Rs 90), and the desk showed the per-player figure while /extraBooking
        # charged three times it.
        gross = gross * multiplier
        hourly = hourly * multiplier
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
        "pricing_source": source,
        "rate_card": epp_summary(card) if source == "rate_card" else None,
        "booked_minutes": round(booked_seconds / 60.0, 2),
        "players": players,
        "squad_multiplier": multiplier,
        # amount is the whole squad's price (rate card, or slot rate x squad
        # multiplier), so /extraBooking must not multiply it again.
        "amount_covers_squad": source == "rate_card" or multiplier > 1,
        "needs_end_time": played_until is None and seconds > STALE_OVERTIME_SECONDS,
        "stale_after_seconds": STALE_OVERTIME_SECONDS,
        "server_time": now.isoformat(),
    }


def epp_summary(card):
    from services.extra_play_pricing import card_summary
    return card_summary(card)


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
