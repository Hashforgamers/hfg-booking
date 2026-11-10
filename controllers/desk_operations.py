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
from services.desk_pricing import validate_definition, legacy_definition, quote

desk = Blueprint("desk_operations", __name__)
@desk.errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    current_app.logger.exception("Desk operations database request failed")
    code = getattr(getattr(error, "orig", None), "pgcode", None)
    if code in ("42P01", "42703", "42P10", "23502"):
        return jsonify(error="Booking database setup is incomplete. Apply the latest desk pricing and history migrations to the booking database, then retry. No rows in this batch were saved."), 503
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
    rows = db.session.execute(text("""SELECT c.game_id,c.profile,c.rates,c.is_active,c.definition,c.archived,c.revision,
        COALESCE(s.mode,'slot') AS pricing_mode FROM desk_rate_cards c
        LEFT JOIN desk_pricing_settings s ON s.vendor_id=c.vendor_id AND s.game_id=c.game_id WHERE c.vendor_id=:vendor"""), {"vendor": vendor_id})
    cards = []
    for row in rows.mappings():
        card = dict(row)
        card["definition"] = card["definition"] or legacy_definition(card["profile"], card["rates"])
        cards.append(card)
    return jsonify(cards)


@desk.put("/vendor/<int:vendor_id>/desk-rates")
@require_vendor_permission("pricing.manage")
def save_rates(vendor_id):
    data = request.get_json(silent=True) or {}
    try:
        import re
        profile = data["profile"]
        if not isinstance(profile,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}",profile):
            raise ValueError("Invalid rate identifier.")
        game = int(data["game_id"])
        if not db.session.execute(text("SELECT id FROM available_games WHERE vendor_id=:v AND id=:g FOR UPDATE"),dict(v=vendor_id,g=game)).first():
            raise ValueError("Choose a device at this cafe.")
        existing = db.session.execute(text("SELECT revision FROM desk_rate_cards WHERE vendor_id=:v AND game_id=:g AND profile=:p FOR UPDATE"),dict(v=vendor_id,g=game,p=profile)).scalar()
        if existing is not None and data.get("revision") != existing:
            db.session.rollback()
            return jsonify(error="This rate was changed by another staff member. Reload it before saving."), 409
        if data.get("definition") is not None:
            definition = validate_definition(data["definition"])
            rates = []
        else:
            rates = [float(money(value)) for value in data["rates"]]
            if len(rates) != RATE_COUNTS[profile]:
                raise ValueError("Invalid legacy rate card.")
            definition = legacy_definition(profile,rates)
        stmt = text("""INSERT INTO desk_rate_cards(vendor_id,game_id,profile,rates,definition,is_active)
            VALUES(:vendor,:game,:profile,:rates,:definition,true)
            ON CONFLICT(vendor_id,game_id,profile) DO UPDATE SET rates=excluded.rates,
                definition=excluded.definition,revision=desk_rate_cards.revision+1
            RETURNING revision""").bindparams(bindparam("rates", type_=JSONB),bindparam("definition",type_=JSONB))
        revision = db.session.execute(stmt,dict(vendor=vendor_id,game=game,profile=profile,rates=rates,definition=definition)).scalar()
        if existing is None:
            db.session.execute(text("""INSERT INTO desk_pricing_settings(vendor_id,game_id,mode)
                VALUES(:v,:g,'variants') ON CONFLICT(vendor_id,game_id) DO UPDATE SET mode='variants'"""),dict(v=vendor_id,g=game))
        db.session.commit()
        return jsonify(success=True,revision=revision)
    except (KeyError, ValueError, TypeError, InvalidOperation) as error:
        db.session.rollback()
        return jsonify(error=str(error) if isinstance(error,ValueError) else "Check the selected device and rates."), 400


@desk.patch("/vendor/<int:vendor_id>/desk-rates")
@require_vendor_permission("pricing.manage")
def maintain_rate(vendor_id):
    data = request.get_json(silent=True) or {}
    try:
        if not any(key in data for key in ("archived", "is_active")) or any(key in data and not isinstance(data[key],bool) for key in ("archived", "is_active")):
            raise ValueError()
        result = db.session.execute(text("""UPDATE desk_rate_cards SET archived=COALESCE(:archived,archived),
            is_active=CASE WHEN COALESCE(:archived,archived) THEN false ELSE COALESCE(:active,is_active) END,
            revision=revision+1
            WHERE vendor_id=:vendor AND game_id=:game AND profile=:profile AND revision=:revision"""),
            dict(archived=data.get('archived'),active=data.get('is_active'),vendor=vendor_id,game=int(data['game_id']),profile=data['profile'],revision=int(data['revision'])))
        if not result.rowcount:
            db.session.rollback()
            return jsonify(error="Rate not found or changed. Reload before trying again."),409
        if data.get('is_active') is True and not data.get('archived'):
            db.session.execute(text("""INSERT INTO desk_pricing_settings(vendor_id,game_id,mode)
                VALUES(:v,:g,'variants') ON CONFLICT(vendor_id,game_id) DO UPDATE SET mode='variants'"""),dict(v=vendor_id,g=int(data['game_id'])))
        db.session.commit()
        return jsonify(success=True)
    except (ValueError,TypeError,KeyError):
        db.session.rollback()
        return jsonify(error="Choose a saved rate to maintain."),400


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
        if data["mode"] == "variants" and not db.session.execute(text("SELECT 1 FROM desk_rate_cards WHERE vendor_id=:v AND game_id=:g AND archived=false AND is_active=true LIMIT 1"),dict(v=vendor_id,g=game)).first():
            db.session.rollback()
            return jsonify(error="Enable or create a rate card before switching to custom pricing."),400
        db.session.execute(text("""INSERT INTO desk_pricing_settings(vendor_id,game_id,mode)
            VALUES(:v,:g,:mode) ON CONFLICT(vendor_id,game_id) DO UPDATE SET mode=excluded.mode"""),dict(v=vendor_id,g=game,mode=data['mode']))
        db.session.commit()
        return jsonify(success=True)
    except (KeyError, TypeError, ValueError):
        db.session.rollback()
        return jsonify(error="Choose slot or variant pricing for a device."), 400


def get_desk_card(vendor, game, profile):
    row = db.session.execute(text("""SELECT c.definition,c.rates,c.profile,c.revision FROM desk_rate_cards c
        JOIN desk_pricing_settings s ON s.vendor_id=c.vendor_id AND s.game_id=c.game_id AND s.mode='variants'
        WHERE c.vendor_id=:v AND c.game_id=:g AND c.profile=:p AND c.is_active=true AND c.archived=false"""),dict(v=vendor,g=game,p=profile)).mappings().first()
    if not row:
        raise ValueError("This rate is no longer active. Refresh and choose a current rate.")
    return dict(definition=row['definition'] or legacy_definition(row['profile'],row['rates']),revision=row['revision'])


def desk_slot_prices(vendor, game, profile, players, slots, revision=None):
    card = get_desk_card(vendor,game,profile)
    if revision is not None and revision != card['revision']:
        raise ValueError("The rate changed. Refresh and review the new price.")
    minutes = {}
    for slot in slots:
        duration = datetime.combine(date.min, slot.end_time) - datetime.combine(date.min, slot.start_time)
        minutes[slot.id] = Decimal(duration.seconds or 86400) / 60
    total_minutes = sum(minutes.values())
    total_price = quote(card['definition'],total_minutes,players)
    from decimal import ROUND_HALF_UP
    elapsed = Decimal(0)
    charged = Decimal(0)
    prices = {}
    for slot_id, duration in minutes.items():
        elapsed += duration
        subtotal = (total_price * elapsed / total_minutes).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        prices[slot_id] = float(subtotal-charged)
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
