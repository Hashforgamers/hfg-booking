"""Flex-start ("any minute") bookings: settings, quote and arrival re-timing.

Creating a flex booking goes through the existing desk endpoint
POST /api/newBooking/vendor/<id> with ``timingMode: "flex"`` so payments,
meals, squads, taxes and receipts stay on one path.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from types import SimpleNamespace

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import text

from db.extensions import db
from services import flex_booking
from services import flex_timing as ft
from services.flex_timing import FlexError
from services.vendor_access import require_vendor_permission

flex_blueprint = Blueprint("flex_booking", __name__)


def flex_error_response(error):
    body = {"success": False, "code": error.code, "message": str(error)}
    body.update(error.details)
    return jsonify(body), error.status


@flex_blueprint.errorhandler(FlexError)
def _handle_flex_error(error):
    db.session.rollback()
    return flex_error_response(error)


def now_ist():
    return datetime.now(ft.IST).replace(tzinfo=None)


def _game(vendor_id, game_id):
    try:
        game_id = int(game_id)
    except (TypeError, ValueError):
        raise FlexError("Choose a device type (gameId).", 400, "invalid_game")
    if isinstance(game_id, bool) or game_id <= 0:
        raise FlexError("Choose a device type (gameId).", 400, "invalid_game")
    row = db.session.execute(text("""SELECT id,vendor_id,game_name,single_slot_price FROM available_games
        WHERE id=:g AND vendor_id=:v"""), {"g": game_id, "v": int(vendor_id)}).mappings().first()
    if not row:
        raise FlexError("This device type does not belong to the cafe.", 404, "invalid_game")
    return SimpleNamespace(**row)


def squad_rules(vendor_id, game, players, squad_enabled):
    """Units (stations) and pricing multiplier/discount, using the desk booking helpers."""
    from controllers.booking_controller import (
        _requires_multi_console_units, _resolve_squad_pricing_mode,
        _resolve_squad_discount_percent, _load_squad_pricing_policy,
    )
    players = max(1, int(players or 1))
    name = game.game_name or ""
    multi = bool(squad_enabled and players > 1 and _requires_multi_console_units(name, vendor_id=vendor_id))
    discount = 0.0
    if squad_enabled and players > 1 and _resolve_squad_pricing_mode(name, vendor_id=vendor_id) == "squad_discount":
        discount = float(_resolve_squad_discount_percent(name, players, policy=_load_squad_pricing_policy(vendor_id),
                                                         vendor_id=vendor_id) or 0.0)
    return {"players": players, "units": players if multi else 1,
            "multiplier": players if multi else 1, "discount_percent": discount}


def window_price(vendor_id, game, plan, occurrences, settings, players, squad, desk_profile=None,
                 desk_revision=None, pricing_game=None, previous_minutes=0):
    """Gaming price for a window. Rate card when the desk picked one, prorated slot price otherwise.

    previous_minutes > 0 prices an extension marginally: price(prev + new) - price(prev).
    """
    minutes = plan.minutes
    if desk_profile:
        from controllers.desk_operations import desk_minutes_price
        def card_total(total):
            return Decimal(str(desk_minutes_price(vendor_id, game.id, desk_profile, squad["players"], total,
                                                  revision=desk_revision, pricing_game=pricing_game)))
        total = card_total(previous_minutes + minutes) - (card_total(previous_minutes) if previous_minutes else 0)
        total = max(Decimal("0"), total)
        return {"basis": "rate_card", "unit_price": float(total), "base_amount": float(total),
                "squad_discount_percent": 0.0, "squad_discount_amount": 0.0, "net_amount": float(total),
                "billed_minutes": minutes, "players": squad["players"], "multiplier": 1}
    from controllers.booking_controller import get_effective_price_for_schedule
    slot = SimpleNamespace(id=plan.base.slot_id, start_time=plan.base.start.time(), end_time=plan.base.end.time())
    slot_price = get_effective_price_for_schedule(vendor_id, game, plan.base.day, slot) or 0
    slot_minutes = ft.minutes_between(plan.base.start, plan.base.end) or ft.typical_slot_minutes(occurrences)
    # A window crossing into slots with another price (an offer on one of them)
    # pays each slot's own rate for its minutes, not the base slot's rate throughout.
    priced = [(item.start, item.end, slot_price if item.key() == plan.base.key() else
               (get_effective_price_for_schedule(vendor_id, game, item.day, SimpleNamespace(
                   id=item.slot_id, start_time=item.start.time(), end_time=item.end.time())) or 0))
              for item in plan.consumed]
    if len({Decimal(str(price)) for _, _, price in priced}) > 1:
        blended = ft.blended_slot_price(plan.start, plan.end, priced, slot_minutes)
        if blended is not None:
            slot_price = blended
    step = settings["step_minutes"]
    def fallback(total):
        return ft.fallback_price(total, slot_price, slot_minutes, step) if total else Decimal("0")
    unit = max(Decimal("0"), fallback(previous_minutes + minutes) - fallback(previous_minutes))
    base = unit * squad["multiplier"]
    discount = (base * Decimal(str(squad["discount_percent"])) / 100).quantize(Decimal("0.01"))
    return {"basis": "slot_prorated", "unit_price": float(unit), "base_amount": float(base),
            "squad_discount_percent": squad["discount_percent"], "squad_discount_amount": float(discount),
            "net_amount": float(base - discount), "billed_minutes": ft.round_up_to_step(minutes, step),
            "players": squad["players"], "multiplier": squad["multiplier"], "slot_price": float(slot_price),
            "slot_minutes": slot_minutes}


def previous_flex_booking(vendor_id, booking_id, start):
    """An extension must start exactly where the earlier booking (same station) ends."""
    row = db.session.execute(text(f"""SELECT d.book_id,d.console_id,d.user_id,d.date,d.start_time,d.end_time,d.book_status
        FROM VENDOR_{int(vendor_id)}_DASHBOARD d WHERE d.book_id=:b"""), {"b": int(booking_id)}).mappings().first()
    if not row or row["book_status"] not in ("current", "upcoming"):
        raise FlexError("Only an active or upcoming booking can be extended.", 409, "not_extendable")
    left, right = ft.slot_window(row["date"], row["start_time"], row["end_time"])
    if start != right:
        raise FlexError(f"An extension starts when the booking ends ({ft.clock(right)}).", 409, "extension_gap",
                        start_at=ft.iso(right))
    return dict(row, minutes=ft.minutes_between(left, right))


def parse_request(vendor_id, data, now=None):
    settings = flex_booking.require_enabled(vendor_id)
    game = _game(vendor_id, data.get("gameId") if data.get("gameId") is not None else data.get("game_id"))
    minutes = ft.validate_duration(data.get("durationMinutes", data.get("duration_minutes")), settings)
    start = ft.to_ist_naive(data.get("startAt", data.get("start_at")), now)
    return settings, game, start, minutes


def build_quote(vendor_id, data, now=None):
    now = now or now_ist()
    settings, game, start, minutes = parse_request(vendor_id, data, now)
    squad_payload = data.get("squadDetails") if isinstance(data.get("squadDetails"), dict) else {}
    players = data.get("players") or squad_payload.get("playerCount") or 1
    squad = squad_rules(vendor_id, game, players, bool(squad_payload.get("enabled", int(players or 1) > 1)))
    previous = None
    if data.get("extendsBookingId"):
        previous = previous_flex_booking(vendor_id, data["extendsBookingId"], start)
    try:
        plan, occurrences = flex_booking.plan_window(vendor_id, game.id, start, minutes, settings, squad["units"], now)
    except FlexError as error:
        error.details.setdefault("stations", [])
        raise
    exclude = [previous["book_id"]] if previous else []
    stations = flex_booking.stations(vendor_id, game.id, plan, now, exclude)
    if previous and previous["console_id"] and int(previous["console_id"]) > 0:
        stations = [s for s in stations if s["console_id"] == int(previous["console_id"])]
    free = [s["console_id"] for s in stations if s["available"]]
    price = window_price(vendor_id, game, plan, occurrences, settings, squad["players"], squad,
                         data.get("deskProfile"), data.get("deskRevision"), data.get("pricingGame"),
                         previous["minutes"] if previous else 0)
    best = max((s["max_minutes_available"] for s in stations), default=0)
    return {
        "success": True,
        "timing_mode": "flex",
        "game_id": game.id,
        "window": {"start_at": ft.iso(plan.start), "end_at": ft.iso(plan.end), "date": plan.start.date().isoformat(),
                   "start": ft.clock(plan.start), "end": ft.clock(plan.end), "duration_minutes": minutes,
                   "label": f"{ft.clock(plan.start)} – {ft.clock(plan.end)}",
                   "crosses_midnight": plan.end.date() != plan.start.date()},
        "live": plan.start <= now < plan.end,
        "booked_date": plan.base.day.isoformat(),
        "base_slot_id": plan.base.slot_id,
        "blocked_slots": plan.slot_payload(),
        "units": squad["units"],
        "stations": stations,
        "available": len(free) >= squad["units"],
        "recommended_console_ids": free[:squad["units"]],
        "max_minutes_available": best,
        "closes_at": ft.iso(plan.close) if plan.close else None,
        "price": price,
        "extends_booking_id": previous["book_id"] if previous else None,
        "settings": settings,
    }


@flex_blueprint.route("/vendor/<int:vendor_id>/flex-booking/settings", methods=["GET"])
@require_vendor_permission("booking.manage")
def get_flex_settings(vendor_id):
    return jsonify(success=True, settings=flex_booking.load_settings(vendor_id),
                   schema_ready=flex_booking.schema_ready())


@flex_blueprint.route("/vendor/<int:vendor_id>/flex-booking/settings", methods=["PUT"])
@require_vendor_permission("account.manage")
def put_flex_settings(vendor_id):
    settings = flex_booking.save_settings(vendor_id, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(success=True, settings=settings)


@flex_blueprint.route("/vendor/<int:vendor_id>/flex-booking/quote", methods=["POST"])
@require_vendor_permission("booking.manage")
def flex_quote(vendor_id):
    data = request.get_json(silent=True) or {}
    result = build_quote(vendor_id, data)
    db.session.rollback()  # read-only; release any row snapshots
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


def retime_arrival(vendor_id, booking_id, data, now=None):
    """Late or early arrival for an upcoming booking: move its window, keep its price."""
    now = now or now_ist()
    settings = flex_booking.require_enabled(vendor_id)
    booking = db.session.execute(text("""SELECT b.id,b.slot_id,b.game_id,b.squad_details FROM bookings b
        JOIN available_games g ON g.id=b.game_id AND g.vendor_id=:v
        WHERE b.id=:b FOR UPDATE OF b"""), {"b": int(booking_id), "v": int(vendor_id)}).mappings().first()
    booking = SimpleNamespace(**booking) if booking else None
    row = db.session.execute(text(f"""SELECT book_id,user_id,console_id,date,start_time,end_time,book_status,game_id
        FROM VENDOR_{int(vendor_id)}_DASHBOARD WHERE book_id=:b FOR UPDATE"""), {"b": int(booking_id)}).mappings().first()
    if not booking or not row:
        raise FlexError("Booking not found for this cafe.", 404, "not_found")
    if row["book_status"] != "upcoming":
        raise FlexError("Only a booking that has not started can be re-timed.", 409, "not_upcoming")
    arrived = ft.to_ist_naive(data.get("arrivedAt"), now)
    policy = data.get("policy") or settings["late_arrival_policy"]
    booked_start, booked_end = ft.slot_window(row["date"], row["start_time"], row["end_time"])
    start, end = ft.arrival_window(booked_start, booked_end, arrived, policy)
    if end <= booked_start:
        raise FlexError("Arrived too early to move this booking; create a new session instead.", 409, "too_early")
    if policy == "shift_if_free" and arrived > booked_start:
        follow = db.session.execute(text(f"""SELECT 1 FROM VENDOR_{int(vendor_id)}_DASHBOARD
            WHERE user_id=:u AND book_id<>:b AND book_status='upcoming' AND date=:d AND start_time=:t LIMIT 1"""),
            {"u": row["user_id"], "b": row["book_id"], "d": row["date"], "t": row["end_time"]}).first()
        if follow:
            raise FlexError("This booking continues into another booked slot; use keep_end for late arrival.",
                            409, "chained_booking")
    details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
    from services.slot_capacity import booking_units
    units = booking_units(details)
    occurrences = flex_booking.load_occurrences(vendor_id, booking.game_id, start.date() - timedelta(days=1),
                                                end.date() + timedelta(days=1))
    consumed = ft.overlapped(occurrences, start, end, settings["partial_slot_grace_minutes"], units)
    from datetime import date as _date
    try:
        base_day = _date.fromisoformat(str(details.get("booked_date"))[:10])
    except ValueError:
        base_day = db.session.execute(text("SELECT MIN(booked_date) FROM transactions WHERE booking_id=:b"),
                                      {"b": booking.id}).scalar() or row["date"]
    held_keys = {(base_day, int(booking.slot_id))} | {(h["date"], int(h["slot_id"])) for h in flex_booking.held(vendor_id, booking.id)}
    if (base_day, int(booking.slot_id)) not in {o.key() for o in consumed}:
        raise FlexError("The new window must still cover the booked slot.", 409, "base_not_covered")
    needed = ft.newly_needed(held_keys, consumed)
    flex_booking.lock_consumed(vendor_id, needed, units)
    plan = ft.Plan(start=start, end=end, minutes=ft.minutes_between(start, end), consumed=consumed,
                   base=next(o for o in consumed if o.key() == (base_day, int(booking.slot_id))))
    requested = [int(row["console_id"])] if row["console_id"] and int(row["console_id"]) > 0 else None
    console_ids, _ = flex_booking.pick_consoles(vendor_id, booking.game_id, plan, 1, requested, now, [booking.id])
    flex_booking.hold_extra(vendor_id, booking.id, needed, units)
    stale = {(o.day, o.slot_id) for o in ft.released_after(
        [o for o in occurrences if o.key() in held_keys - {(base_day, int(booking.slot_id))}], end)}
    if stale:
        flex_booking.release_holds(vendor_id, booking.id, stale)
    db.session.execute(text(f"""UPDATE VENDOR_{int(vendor_id)}_DASHBOARD SET date=:d,start_time=:s,end_time=:e,console_id=:c
        WHERE book_id=:b"""), {"d": start.date(), "s": start.time(), "e": end.time(), "c": console_ids[0], "b": booking.id})
    flex_booking.write_timing(booking.id, start, end)
    return {"success": True, "booking_id": booking.id, "timing_mode": "flex", "policy": policy,
            "start_at": ft.iso(start), "end_at": ft.iso(end), "console_id": console_ids[0],
            "added_slots": [{"slot_id": o.slot_id, "date": o.day.isoformat()} for o in needed],
            "released_slots": [{"slot_id": s, "date": d.isoformat()} for d, s in sorted(stale)],
            "price_change": 0.0}


@flex_blueprint.route("/vendor/<int:vendor_id>/flex-booking/<int:booking_id>/arrival", methods=["POST"])
@require_vendor_permission("booking.manage")
def flex_arrival(vendor_id, booking_id):
    result = retime_arrival(vendor_id, booking_id, request.get_json(silent=True) or {})
    db.session.commit()
    try:
        from utils.realtime import emit_vendor_event
        emit_vendor_event(current_app.extensions.get("socketio"), "booking_updated",
                          {"booking_id": booking_id, "bookingId": booking_id, "status": "confirmed",
                           "timing_mode": "flex", "start_at": result["start_at"], "end_at": result["end_at"]},
                          vendor_id)
    except Exception:
        current_app.logger.warning("flex arrival emit failed booking=%s", booking_id)
    return jsonify(result)
