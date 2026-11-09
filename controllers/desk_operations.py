from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import bindparam

from db.extensions import db
from services.vendor_access import require_vendor_permission

desk = Blueprint("desk_operations", __name__)
@desk.errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    current_app.logger.exception("Desk operations database request failed")
    code = getattr(getattr(error, "orig", None), "pgcode", None)
    if code in ("42P01", "42703", "42P10", "23502"):
        return jsonify(error="Booking database setup is incomplete. Apply the desk rates/history and imported transactions migrations to the booking database, then retry. No rows in this batch were saved."), 503
    return jsonify(error="Could not save or load desk data. Please retry. No rows in this batch were saved."), 503


RATE_COUNTS = {"pc": 3, "ps55": 4, "ps65": 4, "gta55": 1, "gta65": 1, "racing": 2}


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or not 0 <= amount <= 99999999 or amount != amount.quantize(Decimal(".01")):
        raise ValueError("Enter a valid amount with up to two decimal places.")
    return amount


@desk.get("/vendor/<int:vendor_id>/desk-rates")
@require_vendor_permission("booking.manage", "pricing.manage")
def desk_rates(vendor_id):
    rows = db.session.execute(text("SELECT game_id,profile,rates,is_active FROM desk_rate_cards WHERE vendor_id=:vendor"), {"vendor": vendor_id})
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
        db.session.execute(text("UPDATE desk_rate_cards SET is_active=true WHERE vendor_id=:vendor AND game_id=:game"), dict(vendor=vendor_id,game=int(data["game_id"])))
        db.session.commit()
        return jsonify(success=True)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        db.session.rollback()
        return jsonify(error="Check the selected device and rates."), 400


@desk.put("/vendor/<int:vendor_id>/desk-rates/mode")
@require_vendor_permission("pricing.manage")
def set_rate_mode(vendor_id):
    data = request.get_json(silent=True) or {}
    try:
        game = int(data["game_id"])
        if data["mode"] not in ("slot", "variants"):
            raise ValueError()
        if not db.session.execute(text("SELECT id FROM available_games WHERE vendor_id=:vendor AND id=:game"), dict(vendor=vendor_id,game=game)).first():
            raise ValueError()
        changed = db.session.execute(text("UPDATE desk_rate_cards SET is_active=:active WHERE vendor_id=:vendor AND game_id=:game"),
                           dict(active=data["mode"] == "variants", vendor=vendor_id, game=game))
        if data["mode"] == "variants" and not changed.rowcount:
            db.session.rollback()
            return jsonify(error="Save at least one variant rate before enabling variant pricing."), 400
        db.session.commit()
        return jsonify(success=True)
    except (KeyError, TypeError, ValueError):
        db.session.rollback()
        return jsonify(error="Choose slot or variant pricing for a device."), 400


def desk_slot_prices(vendor, game, profile, players, slots):
    rates = db.session.execute(text("SELECT rates FROM desk_rate_cards WHERE vendor_id=:v AND game_id=:g AND profile=:p AND is_active=true"),
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
            payment_status = row.get("paymentStatus")
            if payment_status is not None and str(payment_status).strip().lower() not in ("paid", "completed", "settled", "success", "successful"):
                return jsonify(error=f"Row {index}: payment is not settled. Import only verified payments received."), 400
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
    # Mirror the persisted archive value so a retry cannot change a previously recorded payment.
    from sqlalchemy import bindparam
    posted = db.session.execute(text("""
        INSERT INTO transactions (vendor_id,reference_id,user_name,booked_date,booking_date,booking_time,
            amount,original_amount,discounted_amount,mode_of_payment,payment_use_case,booking_type,
            settlement_status,source_channel,base_amount,meals_amount,controller_amount,waive_off_amount,
            app_fee_amount,taxable_amount,gst_rate,cgst_amount,sgst_amount,igst_amount,total_with_tax,created_at,updated_at)
        SELECT vendor_id,source_key,player,played_on,played_on + (ended < started)::integer,ended,
            paid,paid,0,'Unspecified','historical_payment','historical_session','completed','excel_import',
            paid,0,0,0,0,0,0,0,0,0,paid,now(),now()
        FROM desk_booking_archive WHERE vendor_id=:vendor AND source_key IN :keys
        ON CONFLICT (vendor_id,reference_id) WHERE source_channel='excel_import' DO UPDATE
        SET user_name=excluded.user_name,booked_date=excluded.booked_date,booking_date=excluded.booking_date,
            booking_time=excluded.booking_time,amount=excluded.amount,original_amount=excluded.amount,
            base_amount=excluded.amount,total_with_tax=excluded.amount,updated_at=now()
        WHERE (transactions.user_name,transactions.booked_date,transactions.booking_date,transactions.booking_time,transactions.amount)
              IS DISTINCT FROM (excluded.user_name,excluded.booked_date,excluded.booking_date,excluded.booking_time,excluded.amount)
    """).bindparams(bindparam("keys", expanding=True)), {"vendor":vendor_id, "keys":[p["key"] for p in parameters]})
    db.session.commit()
    return jsonify(inserted=inserted, skipped=len(rows)-inserted, transactions_saved=posted.rowcount)


@desk.get("/vendor/<int:vendor_id>/desk-history")
@require_vendor_permission("booking.manage")
def list_history(vendor_id):
    offset = max(0, request.args.get("offset", 0, type=int))
    rows = db.session.execute(text("""SELECT source_key as key, player, device, played_on::text as date,
        to_char(started,'HH24:MI') as start,to_char(ended,'HH24:MI') as end,paid::text as paid
        FROM desk_booking_archive WHERE vendor_id=:v ORDER BY played_on DESC, source_key LIMIT 50 OFFSET :offset"""),
        dict(v=vendor_id, offset=offset))
    return jsonify([dict(row) for row in rows.mappings()])
