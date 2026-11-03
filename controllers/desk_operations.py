from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import bindparam

from db.extensions import db
from services.vendor_access import require_vendor_permission

desk = Blueprint("desk_operations", __name__)
RATE_COUNTS = {"pc": 3, "ps55": 4, "ps65": 4, "gta55": 1, "gta65": 1, "racing": 2}


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or not 0 <= amount <= 99999999 or amount != amount.quantize(Decimal(".01")):
        raise ValueError("Enter a valid amount with up to two decimal places.")
    return amount


@desk.get("/vendor/<int:vendor_id>/desk-rates")
@require_vendor_permission("booking.manage", "pricing.manage")
def desk_rates(vendor_id):
    rows = db.session.execute(text("SELECT game_id,profile,rates FROM desk_rate_cards WHERE vendor_id=:vendor"), {"vendor": vendor_id})
    return jsonify([dict(row) for row in rows.mappings()])


@desk.put("/vendor/<int:vendor_id>/desk-rates")
@require_vendor_permission("pricing.manage")
def save_rates(vendor_id):
    data = request.get_json()
    try:
        profile = data["profile"]
        rates = [float(money(value)) for value in data["rates"]]
        if len(rates) != RATE_COUNTS[profile]:
            raise ValueError("Invalid rate card.")
        stmt = text("""INSERT INTO desk_rate_cards(vendor_id,game_id,profile,rates)
            SELECT :vendor,id,:profile,:rates FROM available_games WHERE vendor_id=:vendor AND id=:game
            ON CONFLICT(vendor_id,game_id,profile) DO UPDATE SET rates=excluded.rates""").bindparams(bindparam("rates", type_=JSONB))
        if not db.session.execute(stmt, dict(vendor=vendor_id, game=int(data["game_id"]), profile=profile, rates=rates)).rowcount:
            raise ValueError("Choose a device at this cafe.")
        db.session.commit()
        return jsonify(success=True)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        db.session.rollback()
        return jsonify(error="Check the selected device and rates."), 400


def desk_slot_prices(vendor, game, profile, players, slots):
    rates = db.session.execute(text("SELECT rates FROM desk_rate_cards WHERE vendor_id=:v AND game_id=:g AND profile=:p"),
                               dict(v=vendor, g=game, p=profile)).scalar()
    if not rates or profile not in RATE_COUNTS:
        raise ValueError("Refresh the desk rate card.")
    rates = [Decimal(str(rate)) for rate in rates]
    minutes = {}
    for slot in slots:
        duration = datetime.combine(date.min, slot.end_time) - datetime.combine(date.min, slot.start_time)
        minutes[slot.id] = Decimal(duration.seconds or 86400) / 60
    total = sum(minutes.values())
    if profile == "pc":
        hourly = rates[2 if total > 180 else 1 if total >= 120 else 0] * players
    elif profile == "racing":
        if total not in (30, 60) or players != 1:
            raise ValueError("Select 30 or 60 minutes for one racing player.")
        hourly = rates[0] * 2 if total == 30 else rates[1]
    else:
        if not 1 <= players <= len(rates):
            raise ValueError("Player count is outside this rate card.")
        hourly = rates[players - 1] * players
    from decimal import ROUND_HALF_UP
    # Round cumulative amounts so splitting a session into slots never changes its bill.
    elapsed = Decimal(0)
    charged = Decimal(0)
    prices = {}
    for slot_id, duration in minutes.items():
        elapsed += duration
        subtotal = (hourly * elapsed / 60).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        prices[slot_id] = float(subtotal - charged)
        charged = subtotal
    return prices


@desk.route("/vendor/<int:vendor_id>/desk-history", methods=["POST", "PATCH"])
@require_vendor_permission("booking.manage")
def import_history(vendor_id):
    rows = request.get_json().get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        return jsonify(error="Import between 1 and 500 rows per batch."), 400
    parameters = []
    now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    for index, row in enumerate(rows, 1):
        try:
            key, player, device = (row[k].strip() for k in ("key", "player", "device"))
            if not (0 < len(key) <= 100 and 0 < len(player) <= 150 and 0 < len(device) <= 100):
                raise ValueError()
            day = date.fromisoformat(row["date"])
            start, end = (datetime.strptime(row[k], "%H:%M").time() for k in ("start", "end"))
            if start == end or datetime.combine(day, end) + timedelta(days=end < start) > now:
                raise ValueError()
            paid = money(row["paid"])
            parameters.append(dict(v=vendor_id,key=key,player=player,device=device,day=day,start=start,end=end,paid=paid))
        except (KeyError, TypeError, AttributeError, ValueError, InvalidOperation):
            db.session.rollback()
            return jsonify(error=f"Check row {index}: enter a completed session and valid amount."), 400
    if request.method == "PATCH":
        result = db.session.execute(text("""UPDATE desk_booking_archive SET player=:player,device=:device,
            played_on=:day,started=:start,ended=:end,paid=:paid WHERE vendor_id=:v AND source_key=:key"""), parameters)
        inserted = result.rowcount
        if inserted != len(parameters):
            db.session.rollback()
            return jsonify(error="An imported record no longer exists."), 409
    else:
        # Use one INSERT per batch and count only keys that were actually added.
        from sqlalchemy import column, table
        from sqlalchemy.dialects.postgresql import insert
        archive = table("desk_booking_archive", *(column(name) for name in
            ("vendor_id","source_key","player","device","played_on","started","ended","paid")))
        values = [dict(vendor_id=p["v"],source_key=p["key"],player=p["player"],device=p["device"],
                       played_on=p["day"],started=p["start"],ended=p["end"],paid=p["paid"]) for p in parameters]
        statement = insert(archive).values(values).on_conflict_do_nothing(
            index_elements=["vendor_id","source_key"]).returning(archive.c.source_key)
        inserted = len(db.session.execute(statement).all())
    db.session.commit()
    return jsonify(inserted=inserted, skipped=len(rows)-inserted)


@desk.get("/vendor/<int:vendor_id>/desk-history")
@require_vendor_permission("booking.manage")
def list_history(vendor_id):
    offset = max(0, request.args.get("offset", 0, type=int))
    rows = db.session.execute(text("""SELECT source_key as key, player, device, played_on::text as date,
        to_char(started,'HH24:MI') as start,to_char(ended,'HH24:MI') as end,paid::text as paid
        FROM desk_booking_archive WHERE vendor_id=:v ORDER BY played_on DESC, source_key LIMIT 50 OFFSET :offset"""),
        dict(v=vendor_id, offset=offset))
    return jsonify([dict(row) for row in rows.mappings()])
