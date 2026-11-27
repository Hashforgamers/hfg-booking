"""Unused paid time when a desk session ends before its booked end.

The rule and each cafe's policy live here, in one place:

* Value: pro-rata on what the gaming time actually cost the gamer (squad
  discount, rate card and staff discount already applied), on the share that
  was paid. Gaming still unpaid (pay after session) is reduced instead.
* Whole rupees (half up). Nothing when fewer than the cafe's minimum unused
  minutes are left (default 5).
* Policy per cafe (``vendor_unused_time_settings``; no row = default):
    credit_default  return as cafe wallet credit, staff may refund cash instead
    credit          always cafe wallet credit
    refund          always refund to the original payment method
    none            no return, the PC is just freed
* Every return is recorded twice for audit: a negative transaction on the
  booking (booking_type early_release_credit / early_release_refund) and, for
  credit, a cafe wallet ledger entry. The booking keeps the full breakdown in
  squad_details["early_release"] so history can show it.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib

from sqlalchemy import text

POLICIES = ("credit_default", "credit", "refund", "none")
DEFAULT_POLICY = "credit_default"
DEFAULT_MIN_UNUSED_MINUTES = 5
MAX_MIN_UNUSED_MINUTES = 60
REFUND_METHODS = ("cash", "upi", "card")
CREDIT_TYPE = "early_release_credit"
REFUND_TYPE = "early_release_refund"
RETURN_TYPES = {CREDIT_TYPE, REFUND_TYPE}
NON_GAMING_TYPES = {"extra", "additional_meals", "extra_controller", "settlement_waive_off"} | RETURN_TYPES
SETTLED = {"completed", "done", "settled", "paid"}
PENDING = {"pending", "unpaid", "due"}
VOID = {"cancelled", "canceled", "refunded", "reversed", "rejected"}
_MODES = {
    "credit_default": ("credit", "refund"),
    "credit": ("credit",),
    "refund": ("refund",),
    "none": ("none",),
}


class EarlyReleaseError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def allowed_modes(policy):
    return _MODES.get(policy, _MODES[DEFAULT_POLICY])


def default_mode(policy):
    return allowed_modes(policy)[0]


def default_settings():
    return {"policy": DEFAULT_POLICY, "min_unused_minutes": DEFAULT_MIN_UNUSED_MINUTES}


def normalize_settings(payload, current=None):
    merged = dict(current or default_settings())
    payload = payload if isinstance(payload, dict) else {}
    if "policy" in payload:
        policy = str(payload.get("policy") or "").strip().lower()
        if policy not in POLICIES:
            raise EarlyReleaseError("Choose one of: " + ", ".join(POLICIES))
        merged["policy"] = policy
    if "min_unused_minutes" in payload:
        try:
            minutes = int(payload.get("min_unused_minutes"))
        except (TypeError, ValueError):
            raise EarlyReleaseError("Minimum unused minutes must be a whole number")
        if isinstance(payload.get("min_unused_minutes"), bool) or not 0 <= minutes <= MAX_MIN_UNUSED_MINUTES:
            raise EarlyReleaseError(f"Minimum unused minutes must be 0 to {MAX_MIN_UNUSED_MINUTES}")
        merged["min_unused_minutes"] = minutes
    return merged


def unused_value(paid, booked_minutes, unused_minutes, min_unused=DEFAULT_MIN_UNUSED_MINUTES):
    """Whole rupees owed back for unused minutes of a booking that cost ``paid``."""
    paid = Decimal(str(paid or 0))
    if paid <= 0 or booked_minutes <= 0 or unused_minutes <= 0 or unused_minutes < min_unused:
        return 0
    unused = min(Decimal(str(unused_minutes)), Decimal(str(booked_minutes)))
    return int((paid * unused / Decimal(str(booked_minutes))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gaming_amounts(lines):
    """(paid, pending, method) of the gaming lines, net of food/controller share.

    lines: dicts with booking_type, settlement_status, amount, meals_amount,
    controller_amount, mode_of_payment. Extra time, food, controllers, bill
    waivers and earlier returns are not gaming time.
    """
    paid, pending = Decimal("0"), Decimal("0")
    by_method = {}
    for line in lines or []:
        kind = str(line.get("booking_type") or "").strip().lower()
        status = str(line.get("settlement_status") or "").strip().lower()
        if kind in NON_GAMING_TYPES or status in VOID:
            continue
        amount = Decimal(str(line.get("amount") or 0))
        amount -= Decimal(str(line.get("meals_amount") or 0)) + Decimal(str(line.get("controller_amount") or 0))
        amount = max(amount, Decimal("0"))
        if status in SETTLED:
            paid += amount
            method = str(line.get("mode_of_payment") or "cash").strip().lower()
            by_method[method] = by_method.get(method, Decimal("0")) + amount
        elif status in PENDING:
            pending += amount
    method = max(by_method, key=by_method.get) if by_method else None
    q = lambda d: float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return q(paid), q(pending), method


def refund_method_for(original):
    value = str(original or "").strip().lower()
    if "upi" in value:
        return "upi"
    if "card" in value:
        return "card"
    return "cash"


def breakdown(booked_start, booked_end, booked_seconds, ended_at, paid, pending, settings):
    """Pure figures for the receipt. Minutes are whole: play rounds down, so unused rounds up."""
    booked_minutes = int(round((booked_seconds or (booked_end - booked_start).total_seconds()) / 60.0))
    ended = min(max(ended_at, booked_start), booked_end)
    played_minutes = int((ended - booked_start).total_seconds() // 60)
    unused_minutes = max(0, booked_minutes - played_minutes)
    minimum = int(settings.get("min_unused_minutes", DEFAULT_MIN_UNUSED_MINUTES))
    paid_back = unused_value(paid, booked_minutes, unused_minutes, minimum)
    due_cut = unused_value(pending, booked_minutes, unused_minutes, minimum)
    policy = settings.get("policy", DEFAULT_POLICY)
    if policy == "none":
        paid_back = due_cut = 0
    return {
        "booked_minutes": booked_minutes,
        "played_minutes": played_minutes,
        "unused_minutes": unused_minutes,
        "eligible": unused_minutes > 0 and unused_minutes >= minimum,
        "paid_amount": paid,
        "pending_amount": pending,
        "return_amount": paid_back,
        "pending_reduction": due_cut,
    }


# ----------------------------------------------------------------- database


def schema_ready(session):
    return bool(session.execute(text("SELECT to_regclass('vendor_unused_time_settings') IS NOT NULL")).scalar())


def load_settings(session, vendor_id):
    settings = default_settings()
    if not schema_ready(session):
        return settings
    row = session.execute(text("""SELECT policy,min_unused_minutes FROM vendor_unused_time_settings
        WHERE vendor_id=:v"""), {"v": int(vendor_id)}).mappings().first()
    if row:
        settings.update({k: row[k] for k in settings if row[k] is not None})
    return settings


def save_settings(session, vendor_id, payload):
    if not schema_ready(session):
        raise EarlyReleaseError("Apply sql/20261127_unused_time_policy.sql before changing this setting.", 503)
    merged = normalize_settings(payload, load_settings(session, vendor_id))
    session.execute(text("""INSERT INTO vendor_unused_time_settings(vendor_id,policy,min_unused_minutes,updated_at)
        VALUES(:v,:policy,:min_unused_minutes,now())
        ON CONFLICT(vendor_id) DO UPDATE SET policy=excluded.policy,
          min_unused_minutes=excluded.min_unused_minutes, updated_at=now()"""),
        dict(merged, v=int(vendor_id)))
    return merged


def _chain(session, vendor_id, booking, console_id):
    """Booked window of the back-to-back bookings shown as one session, and their ids."""
    from services.overtime_quote import chain_bounds, _span
    table = f"VENDOR_{int(vendor_id)}_DASHBOARD"
    own = session.execute(text(f"""SELECT book_id,user_id,console_id,date,start_time,end_time,book_status
        FROM {table} WHERE book_id=:bid ORDER BY start_time"""), {"bid": booking.id}).mappings().all()
    if console_id is not None:
        own = [r for r in own if r["console_id"] is None or str(r["console_id"]) == str(console_id)] or own
    if not own:
        raise EarlyReleaseError("Booking is not on this cafe's dashboard", 404)
    first = own[0]
    rows = session.execute(text(f"""SELECT book_id,date,start_time,end_time FROM {table}
        WHERE user_id=:uid AND date BETWEEN :day AND :next_day
          AND (CAST(:cid AS integer) IS NULL OR console_id=:cid)
          AND book_status IN ('current','upcoming')"""),
        {"uid": first["user_id"], "day": first["date"], "next_day": first["date"] + timedelta(days=1),
         "cid": first["console_id"]}).mappings().all()
    rows = [dict(r) for r in rows] + [dict(r) for r in own]
    start, end, seconds = chain_bounds(rows, booking.id)
    ids = sorted({int(r["book_id"]) for r in rows
                  if start <= _span(r["date"], r["start_time"], r["end_time"])[0]
                  and _span(r["date"], r["start_time"], r["end_time"])[1] <= end})
    return start, end, seconds, ids or [int(booking.id)]


def _lines(session, vendor_id, booking_ids):
    rows = session.execute(text("""SELECT booking_type,settlement_status,amount,meals_amount,controller_amount,
            mode_of_payment FROM transactions WHERE booking_id = ANY(:ids) AND vendor_id=:v"""),
        {"ids": list(booking_ids), "v": int(vendor_id)}).mappings().all()
    return [dict(r) for r in rows]


def _recorded(session, booking_ids):
    rows = session.execute(text("SELECT id,squad_details FROM bookings WHERE id = ANY(:ids)"),
                           {"ids": list(booking_ids)}).mappings().all()
    for row in rows:
        details = row["squad_details"] if isinstance(row["squad_details"], dict) else {}
        if isinstance(details.get("early_release"), dict):
            return details["early_release"]
    return None


def quote(session, vendor_id, booking, console_id=None, ended_at=None, now=None):
    from services.overtime_quote import ist_now
    now = now or ist_now()
    ended = ended_at or now
    if ended > now + timedelta(minutes=1):
        raise EarlyReleaseError("Play cannot end in the future")
    settings = load_settings(session, vendor_id)
    start, end, seconds, ids = _chain(session, vendor_id, booking, console_id)
    paid, pending, method = gaming_amounts(_lines(session, vendor_id, ids))
    figures = breakdown(start, end, seconds, ended, paid, pending, settings)
    return {
        "booking_id": int(booking.id),
        "booking_ids": ids,
        "booked_start": start.isoformat(),
        "booked_end": end.isoformat(),
        "ended_at": ended.isoformat(),
        **figures,
        "policy": settings["policy"],
        "min_unused_minutes": settings["min_unused_minutes"],
        "modes": list(allowed_modes(settings["policy"])),
        "default_mode": default_mode(settings["policy"]),
        "original_method": method,
        "refund_method": refund_method_for(method),
        "recorded": _recorded(session, ids),
        "server_time": now.isoformat(),
    }


def _credit_wallet(session, vendor_id, user_id, amount, key, reason, actor_name):
    units = int(Decimal(amount) * 100)
    # Same lock order as cafe_booking_wallet.move and the dashboard service (vendor, then wallet).
    session.execute(text("SELECT pg_advisory_xact_lock(220926,:vid)"), {"vid": int(vendor_id)})
    fingerprint = hashlib.sha256(f"{vendor_id}:{user_id}:{units}:{key}".encode()).hexdigest()
    old = session.execute(text("""SELECT fingerprint FROM cafe_wallet_ledger
        WHERE vendor_id=:vid AND idempotency_key=:key"""), {"vid": vendor_id, "key": key}).scalar()
    if old:
        if old != fingerprint:
            raise EarlyReleaseError("This return was already recorded with a different amount", 409)
        return units
    session.execute(text("""INSERT INTO cafe_wallets(vendor_id,user_id,balance,reserved) VALUES(:vid,:uid,0,0)
        ON CONFLICT DO NOTHING"""), {"vid": vendor_id, "uid": user_id})
    wallet = session.execute(text("""SELECT balance,reserved FROM cafe_wallets
        WHERE vendor_id=:vid AND user_id=:uid FOR UPDATE"""), {"vid": vendor_id, "uid": user_id}).first()
    balance = session.execute(text("""UPDATE cafe_wallets SET balance=balance+:delta
        WHERE vendor_id=:vid AND user_id=:uid RETURNING balance"""),
        {"delta": units, "vid": vendor_id, "uid": user_id}).scalar_one()
    session.execute(text("""INSERT INTO cafe_wallet_ledger(vendor_id,user_id,kind,amount,balance_after,reserved_after,
        actor_id,actor_name,method,reason,idempotency_key,fingerprint,created_at)
        VALUES(:vid,:uid,'adjustment',:amount,:balance,:reserved,'desk',:actor,'early_release',:reason,:key,:fp,
               (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))"""),
        {"vid": vendor_id, "uid": user_id, "amount": units, "balance": balance, "reserved": wallet.reserved,
         "actor": (actor_name or "Desk")[:120], "reason": reason[:500], "key": key, "fp": fingerprint})
    return units


def apply(session, vendor_id, booking, mode=None, refund_method=None, console_id=None, ended_at=None,
          actor=None, now=None, gst=None):
    """Record the return once per session. Amounts are always recomputed here, never taken from the client."""
    actor = actor or {"source_channel": "dashboard", "staff_id": None, "staff_name": None, "staff_role": None}
    figures = quote(session, vendor_id, booking, console_id, ended_at, now)
    if figures["recorded"]:
        return dict(figures["recorded"], already_recorded=True)
    for booking_id in figures["booking_ids"]:  # one return per session, even under concurrent clicks
        session.execute(text("SELECT id FROM bookings WHERE id=:b FOR UPDATE"), {"b": booking_id})
    again = _recorded(session, figures["booking_ids"])
    if again:
        return dict(again, already_recorded=True)
    amount = int(figures["return_amount"])
    mode = str(mode or figures["default_mode"]).strip().lower()
    if amount <= 0:
        mode = "none"
    elif mode not in figures["modes"]:
        raise EarlyReleaseError("This cafe's unused-time setting does not allow " + mode, 409)
    method = None
    if mode == "refund":
        method = str(refund_method or figures["refund_method"]).strip().lower()
        if method not in REFUND_METHODS:
            raise EarlyReleaseError("Refund method must be cash, upi or card")
    primary = int(figures["booking_ids"][0])
    key = f"early-release:{primary}"
    reason = (f"Unused {figures['unused_minutes']} min of booking #{primary} "
              f"(paid Rs {figures['paid_amount']:.2f} for {figures['booked_minutes']} min)")
    transaction_id = None
    if mode in ("credit", "refund"):
        user = session.execute(text("SELECT id,name FROM users WHERE id=:u"), {"u": booking.user_id}).mappings().first()
        if mode == "credit":
            _credit_wallet(session, int(vendor_id), int(booking.user_id), amount, key, reason, actor.get("staff_name"))
        tax = gst(amount) if gst else {}
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        transaction_id = int(session.execute(text("""INSERT INTO transactions(
                booking_id,vendor_id,user_id,booked_date,booking_date,booking_time,user_name,
                original_amount,discounted_amount,amount,mode_of_payment,payment_use_case,booking_type,
                settlement_status,source_channel,initiated_by_staff_id,initiated_by_staff_name,initiated_by_staff_role,
                base_amount,meals_amount,controller_amount,waive_off_amount,app_fee_amount,
                taxable_amount,gst_rate,cgst_amount,sgst_amount,igst_amount,total_with_tax,reference_id,created_at,updated_at)
            VALUES(:booking_id,:vendor_id,:user_id,:day,:day,:time,:user_name,
                :amount,0,:amount,:method,:method,:kind,'completed',:source,:staff_id,:staff_name,:staff_role,
                :amount,0,0,0,0,:taxable,:rate,:cgst,:sgst,:igst,:amount,:ref,:now,:now)
            RETURNING id"""), {
                "booking_id": primary, "vendor_id": int(vendor_id), "user_id": booking.user_id,
                "day": now_utc.date(), "time": now_utc.time(), "user_name": (user["name"] if user else None) or "Gamer",
                "amount": -float(amount), "method": "cafe_wallet" if mode == "credit" else method,
                "kind": CREDIT_TYPE if mode == "credit" else REFUND_TYPE,
                "source": actor.get("source_channel") or "dashboard", "staff_id": actor.get("staff_id"),
                "staff_name": actor.get("staff_name"), "staff_role": actor.get("staff_role"),
                "taxable": -float(tax.get("taxable_amount", amount)), "rate": float(tax.get("gst_rate", 0.0)),
                "cgst": -float(tax.get("cgst_amount", 0.0)), "sgst": -float(tax.get("sgst_amount", 0.0)),
                "igst": -float(tax.get("igst_amount", 0.0)), "ref": key, "now": now_utc,
            }).scalar_one())
    record = {
        "mode": mode,
        "amount": amount if mode != "none" else 0,
        "refund_method": method,
        "transaction_id": transaction_id,
        "booking_ids": figures["booking_ids"],
        "booked_start": figures["booked_start"],
        "booked_end": figures["booked_end"],
        "ended_at": figures["ended_at"],
        "booked_minutes": figures["booked_minutes"],
        "played_minutes": figures["played_minutes"],
        "unused_minutes": figures["unused_minutes"],
        "paid_amount": figures["paid_amount"],
        "pending_reduction": figures["pending_reduction"],
        "unused_value": amount,
        "policy": figures["policy"],
        "staff_name": actor.get("staff_name"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    import json
    rows = session.execute(text("SELECT id,squad_details FROM bookings WHERE id = ANY(:ids)"),
                           {"ids": figures["booking_ids"]}).mappings().all()
    for row in rows:
        details = dict(row["squad_details"]) if isinstance(row["squad_details"], dict) else {}
        details["early_release"] = record
        session.execute(text("UPDATE bookings SET squad_details=CAST(:d AS json) WHERE id=:id"),
                        {"d": json.dumps(details, default=str), "id": row["id"]})
    session.flush()
    return record

