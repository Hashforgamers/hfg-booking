from flask import Blueprint, jsonify, current_app, request
from models.slot import Slot
from services.live_slot_capacity import load_console_holds, free_console_capacity
from services.game_capacity import sync_game_capacity
from services.slot_capacity import booking_units
from flask_socketio import emit
from db.extensions import db
from sqlalchemy.sql import text, bindparam
from sqlalchemy import func, tuple_
from datetime import datetime, timedelta
from models.availableGame import AvailableGame
from models.booking import Booking
from models.transaction import Transaction
from pytz import timezone
import time
import threading


slot_blueprint = Blueprint('slots', __name__)


@slot_blueprint.after_request
def prevent_stale_availability(response):
    # Live console holds can change immediately on checkout or assignment.
    response.headers["Cache-Control"] = "no-store"
    return response

# Operating-hour edits must be visible on the next request across service instances.
SLOTS_BATCH_CACHE_TTL_SEC = 0
SLOTS_SINGLE_CACHE_TTL_SEC = 0
_slots_batch_cache = {}
_slots_batch_cache_lock = threading.Lock()
_slots_single_cache = {}
_slots_single_cache_lock = threading.Lock()
_expected_blocks_cache = {}
_expected_blocks_cache_lock = threading.Lock()


def _force_slot_refresh():
    # Support both explicit refresh and existing dashboard timestamp cache busters.
    return (str(request.args.get("refresh") or request.args.get("no_cache") or "").lower()
            in {"1", "true", "yes"} or bool(request.args.get("t")))


def _slot_duration_minutes(start_time, end_time):
    """Return positive duration in minutes for HH:MM:SS times, handling overnight edge."""
    if not start_time or not end_time:
        return 0
    sh, sm = start_time.hour, start_time.minute
    eh, em = end_time.hour, end_time.minute
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min <= start_min:
        end_min += 24 * 60
    return int(end_min - start_min)


def _load_vendor_day_duration_map(vendor_id):
    rows = db.session.execute(
        text("""
            SELECT day, slot_duration
            FROM vendor_day_slot_config
            WHERE vendor_id = :vendor_id
        """),
        {"vendor_id": vendor_id},
    ).fetchall()
    duration_map = {}
    for row in rows:
        key = str(row.day or "").strip().lower()[:3]
        try:
            duration = int(row.slot_duration or 0)
        except (TypeError, ValueError):
            continue
        if key and duration > 0:
            duration_map[key] = duration
    return duration_map


def _weekday_key_from_yyyymmdd(yyyymmdd):
    dt_obj = datetime.strptime(yyyymmdd, "%Y%m%d")
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt_obj.weekday()]


def _parse_time_flexible(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%I:%M %p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _generate_blocks(anchor_day, start_time, end_time, slot_duration):
    start_dt = datetime.combine(anchor_day, start_time)
    end_dt = datetime.combine(anchor_day, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    blocks = []
    cur_dt = start_dt
    while cur_dt < end_dt:
        nxt_dt = cur_dt + timedelta(minutes=int(slot_duration))
        if nxt_dt > end_dt:
            break
        block_start_t = cur_dt.time()
        block_end_t = nxt_dt.time() if nxt_dt.date() == cur_dt.date() else (nxt_dt - timedelta(days=1)).time()
        blocks.append((block_start_t, block_end_t))
        cur_dt = nxt_dt
    return blocks


def _expected_blocks_for_date(vendor_id, formatted_date):
    cache_key = f"{vendor_id}:{formatted_date}"
    now_ts = time.time()
    with _expected_blocks_cache_lock:
        cached = _expected_blocks_cache.get(cache_key)
    if cached and cached["expires_at"] > now_ts:
        return cached["payload"]

    dt_obj = datetime.strptime(formatted_date, "%Y-%m-%d").date()
    day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt_obj.weekday()]
    opening = db.session.execute(text("""SELECT is_open FROM opening_days
        WHERE vendor_id=:vendor AND lower(substr(trim(day),1,3))=:day"""),
        {'vendor':vendor_id, 'day':day_key}).fetchall()
    if opening and not any(bool(row[0]) for row in opening):
        return set()
    cfg_rows = db.session.execute(
        text(
            """
            SELECT opening_time, closing_time, slot_duration
            FROM vendor_day_slot_config
            WHERE vendor_id = :vendor_id
              AND lower(substr(day, 1, 3)) = :day_key
            """
        ),
        {"vendor_id": vendor_id, "day_key": day_key},
    ).fetchall()
    if not cfg_rows:
        return None

    blocks = []
    for cfg in cfg_rows:
        try:
            duration = int(cfg.slot_duration or 0)
        except (TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        open_t = _parse_time_flexible(cfg.opening_time)
        close_t = _parse_time_flexible(cfg.closing_time)
        if not open_t or not close_t:
            continue
        blocks.extend(_generate_blocks(dt_obj, open_t, close_t, duration))
    payload = set(blocks)
    with _expected_blocks_cache_lock:
        _expected_blocks_cache[cache_key] = {
            "payload": payload,
            "expires_at": now_ts,
        }
    return payload


def _ensure_slots_for_date(vendor_id, game_id, formatted_date):
    """
    Self-heal missing slots for a specific vendor/game/date based on vendor_day_slot_config.
    Keeps data consistent when historical cleanup removed some slot templates.
    """
    expected = _expected_blocks_for_date(vendor_id, formatted_date)
    if not expected:
        return
    blocks = list(expected)

    available_game = AvailableGame.query.filter_by(id=game_id, vendor_id=vendor_id).first()
    total_slots = int(available_game.total_slot or 0) if available_game else 0

    existing = (
        Slot.query
        .filter(
            Slot.gaming_type_id == game_id,
            tuple_(Slot.start_time, Slot.end_time).in_(blocks),
        )
        .all()
    )
    slot_id_map = {(s.start_time, s.end_time): int(s.id) for s in existing}

    to_create = []
    for st, et in blocks:
        if (st, et) in slot_id_map:
            continue
        to_create.append(
            Slot(
                gaming_type_id=game_id,
                start_time=st,
                end_time=et,
                available_slot=max(total_slots, 1),
                is_available=True,
            )
        )
    if to_create:
        db.session.add_all(to_create)
        db.session.flush()
        for s in to_create:
            slot_id_map[(s.start_time, s.end_time)] = int(s.id)

    slot_ids = [slot_id_map[(st, et)] for st, et in blocks if (st, et) in slot_id_map]
    if not slot_ids:
        return

    table_name = f"VENDOR_{vendor_id}_SLOT"
    db.session.execute(
        text(
            f"""
            INSERT INTO {table_name} (vendor_id, date, slot_id, is_available, available_slot)
            SELECT :vendor_id, CAST(:date_val AS date), s_id.slot_id, TRUE, :available_slot
            FROM (SELECT unnest(:slot_ids) AS slot_id) s_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM {table_name} v
                WHERE v.vendor_id = :vendor_id
                  AND v.date = CAST(:date_val AS date)
                  AND v.slot_id = s_id.slot_id
            )
            """
        ),
        {
            "vendor_id": vendor_id,
            "date_val": formatted_date,
            "slot_ids": slot_ids,
            "available_slot": max(total_slots, 1),
        },
    )


def _load_vendor_slot_rows(vendor_id, game_id, formatted_date):
    table_name = f"VENDOR_{vendor_id}_SLOT"
    sql_query = text(f"""
        SELECT
            vs.slot_id,
            vs.is_available,
            vs.available_slot,
            s.start_time,
            s.end_time
        FROM {table_name} vs
        INNER JOIN slots s ON s.id = vs.slot_id
        INNER JOIN available_games ag ON ag.id = s.gaming_type_id
        INNER JOIN available_game_console agc ON agc.available_game_id = ag.id
        INNER JOIN consoles c ON c.id = agc.console_id AND c.vendor_id = :vendor_id
        WHERE vs.date = :date
          AND s.gaming_type_id = :game_id
          AND ag.vendor_id = :vendor_id
        GROUP BY vs.slot_id, vs.is_available, vs.available_slot, s.start_time, s.end_time
        ORDER BY s.start_time ASC;
    """)
    return db.session.execute(
        sql_query,
        {"date": formatted_date, "game_id": game_id, "vendor_id": vendor_id},
    ).fetchall()


def _slot_price_lookup(vendor_id, game_ids, dates):
    """price(game_id, base, day, start, end) -> the price checkout charges for that slot.

    Slot listings used to return the console's base price while every checkout
    (/bookings/confirm, pay-at-cafe accept, dashboard newBooking) charges the
    offer that covers the slot (get_effective_price_for_schedule). The app
    sums the listed price for the Razorpay order, so an active offer made the
    captured amount differ from the booking total and confirmation failed.
    Same rule as services.pricing_math.effective_price; any failure falls back
    to the base price so a listing never breaks.
    """
    from datetime import date as _date
    from types import SimpleNamespace
    from services.pricing_math import effective_price, slot_window
    offers = {}
    try:
        days = sorted(_date.fromisoformat(str(d)[:10]) for d in dates)
        if game_ids and days:
            rows = db.session.execute(text("""SELECT available_game_id,start_date,start_time,end_date,end_time,
                    offered_price,is_active FROM console_pricing_offers
                WHERE vendor_id=:vendor AND available_game_id IN :games AND is_active=true
                  AND start_date <= :last AND end_date >= :first""").bindparams(bindparam("games", expanding=True)),
                {"vendor": int(vendor_id), "games": [int(g) for g in game_ids],
                 "first": days[0] - timedelta(days=1), "last": days[-1] + timedelta(days=1)}).mappings().all()
            for row in rows:
                offers.setdefault(int(row["available_game_id"]), []).append(SimpleNamespace(**dict(row)))
    except Exception as error:
        current_app.logger.warning("slot offer lookup failed vendor_id=%s err=%s", vendor_id, error)
        offers = {}

    def price(game_id, base, day, start, end):
        candidates = offers.get(int(game_id))
        if not candidates or base is None:
            return base
        try:
            day = _date.fromisoformat(str(day)[:10]) if not isinstance(day, _date) else day
            left, right = slot_window(day, start, end)
            value = effective_price(base, candidates, left, right)
            return int(value) if value == int(value) else float(value)
        except Exception:
            return base
    return price


def _prefer_slot_candidate(current, candidate):
    """
    Choose the better slot row when duplicate logical slots exist for same time.
    Preference:
    1) Higher available_slot
    2) is_available = True
    3) Keep existing as stable tie-break
    """
    if current is None:
        return candidate

    curr_avail = int(current.get("available_slot") or 0)
    cand_avail = int(candidate.get("available_slot") or 0)
    if cand_avail > curr_avail:
        return candidate
    if cand_avail < curr_avail:
        return current

    curr_open = bool(current.get("is_available"))
    cand_open = bool(candidate.get("is_available"))
    if cand_open and not curr_open:
        return candidate
    return current


# Bookings in these states no longer hold a console; their slot units were
# already returned (cancel, failed payment, no-show). Counting them made a cafe
# look full long before its consoles were.
RELEASED_BOOKING_STATUSES = (
    "cancelled", "canceled", "rejected", "verification_failed", "discarded",
    "no_show", "expired", "failed", "refunded",
)


def _booking_play_date(squad_details):
    """The date a booking reserved, as stored at creation (booked_date)."""
    details = squad_details
    if isinstance(details, str):
        try:
            import json
            details = json.loads(details)
        except (TypeError, ValueError):
            return None
    if not isinstance(details, dict):
        return None
    value = str(details.get("booked_date") or details.get("book_date") or "").strip()[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def _load_booking_counts(vendor_id, game_ids, formatted_dates):
    """
    Return map {(slot_id, YYYY-MM-DD): console units held by live bookings}
    for selected vendor/game/date window. Squad bookings hold one unit per PC.
    """
    if not game_ids or not formatted_dates:
        return {}

    rows = (
        db.session.query(
            Booking.id,
            Booking.slot_id,
            Booking.squad_details,
            Transaction.booked_date,
        )
        .join(Transaction, Transaction.booking_id == Booking.id)
        .filter(
            Booking.game_id.in_(game_ids),
            Transaction.vendor_id == vendor_id,
            Transaction.booked_date.in_(formatted_dates),
            Booking.slot_id.isnot(None),
            func.lower(func.coalesce(Booking.status, "")).notin_(RELEASED_BOOKING_STATUSES),
        )
        .all()
    )

    # Later adjustments (waive-off, extra time, meals) are dated the day they
    # are recorded. They must not move an old booking onto that day's slot.
    play_dates = {}
    candidate_ids = {int(row.id) for row in rows}
    if candidate_ids:
        play_dates = {
            int(bid): first for bid, first in db.session.query(
                Transaction.booking_id, func.min(Transaction.booked_date)
            ).filter(Transaction.booking_id.in_(candidate_ids)).group_by(Transaction.booking_id).all()
        }

    out = {}
    seen = set()
    for row in rows:
        if not row.slot_id or not row.booked_date or row.id in seen:
            continue
        seen.add(row.id)  # one booking has several transactions (meals, extra time)
        play_date = _booking_play_date(row.squad_details) or play_dates.get(int(row.id)) or row.booked_date
        if hasattr(play_date, "strftime"):
            play_date = play_date.strftime("%Y-%m-%d")
        if str(play_date)[:10] not in formatted_dates:
            continue
        key = (int(row.slot_id), str(play_date)[:10])
        try:
            units = booking_units(row.squad_details)
        except (TypeError, ValueError):
            units = 1
        out[key] = out.get(key, 0) + units
    return out


def _load_qr_held_units(vendor_id, formatted_dates):
    """Units held by self-service QR play (stored in cafe_slot_reservations)."""
    if not formatted_dates:
        return {}
    if not db.session.execute(text("SELECT to_regclass('cafe_slot_reservations')")).scalar():
        return {}
    rows = db.session.execute(text("""
        SELECT slot_id, date, SUM(units) FROM cafe_slot_reservations
        WHERE vendor_id=:vendor AND released_at IS NULL AND date IN :dates
        GROUP BY slot_id, date
    """).bindparams(bindparam("dates", expanding=True)),
        {"vendor": int(vendor_id), "dates": list(formatted_dates)}).fetchall()
    return {(int(r[0]), r[1].strftime("%Y-%m-%d")): int(r[2] or 0) for r in rows}


def _repair_leaked_capacity(vendor_id, slot_id, formatted_date, raw_available, floor):
    """Raise a dated row that lost units to an un-released booking path.

    Only ever raises, only for today onward, and only if nobody changed the row
    since it was read, so a concurrent booking's decrement is never overwritten.
    """
    if floor <= raw_available:
        return raw_available
    try:
        day = datetime.strptime(formatted_date, "%Y-%m-%d").date()
        if day < datetime.now(timezone("Asia/Kolkata")).date():
            return raw_available
        updated = db.session.execute(text(f"""
            UPDATE VENDOR_{int(vendor_id)}_SLOT
            SET available_slot=:floor, is_available=TRUE
            WHERE vendor_id=:vendor AND slot_id=:slot AND date=:day AND available_slot=:raw
        """), {"floor": int(floor), "vendor": int(vendor_id), "slot": int(slot_id),
                "day": day, "raw": int(raw_available)})
        db.session.commit()
        if updated.rowcount == 1:
            current_app.logger.warning(
                "slot_capacity.repaired vendor=%s slot=%s date=%s %s->%s",
                vendor_id, slot_id, formatted_date, raw_available, floor)
            return int(floor)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("slot_capacity.repair_failed vendor=%s slot=%s", vendor_id, slot_id)
    return raw_available

@slot_blueprint.route('/slots', methods=['GET'])
def get_slots():
    try:
        slots = Slot.query.all()
        current_app.logger.info(f"Fetched {len(slots)} slots")
        return jsonify([slot.to_dict() for slot in slots]), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching slots: {str(e)}")
        return jsonify({"error": str(e)}), 400

@slot_blueprint.route('/getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>', methods=['GET'])
def get_slots_on_game_id(vendorId, gameId, date):
    """
    Fetch available slots from the dynamic VENDOR_<vendorId>_SLOT table based on date and gameId.
    Append single_slot_price from available_games.
    """
    try:
        if len(date) != 8 or not date.isdigit():
            return jsonify({"error": "Invalid date format. Use YYYYMMDD."}), 400

        formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        cache_key = f"{vendorId}:{int(gameId)}:{date}"
        now_ts = time.time()
        with _slots_single_cache_lock:
            cached = _slots_single_cache.get(cache_key)
        if not _force_slot_refresh() and cached and cached["expires_at"] > now_ts:
            response = jsonify(cached["payload"])
            response.headers["X-Cache"] = "HIT"
            return response, 200

        # Step 1: Get game price.
        available_game = AvailableGame.query.filter_by(id=gameId, vendor_id=vendorId).first()
        if not available_game:
            return jsonify({"error": "Game not found for this vendor."}), 404

        single_slot_price = available_game.single_slot_price

        result = _load_vendor_slot_rows(vendorId, int(gameId), formatted_date)
        if not result:
            _ensure_slots_for_date(vendorId, int(gameId), formatted_date)
            result = _load_vendor_slot_rows(vendorId, int(gameId), formatted_date)
        if not result:
            payload = {"slots": []}
            with _slots_single_cache_lock:
                _slots_single_cache[cache_key] = {
                    "payload": payload,
                    "expires_at": now_ts + SLOTS_SINGLE_CACHE_TTL_SEC,
                }
            response = jsonify(payload)
            response.headers["X-Cache"] = "MISS"
            return response, 200

        # Capacity is the consoles really mapped to this game, not a stale seed.
        total_slots_for_game = sync_game_capacity(vendorId, int(gameId)) or int(available_game.total_slot or 0)
        booking_counts = _load_booking_counts(vendorId, [int(gameId)], [formatted_date])
        qr_units = _load_qr_held_units(vendorId, [formatted_date])
        live_holds = load_console_holds(vendorId, [int(gameId)])
        expected_blocks = _expected_blocks_for_date(vendorId, formatted_date)

        slot_price = _slot_price_lookup(vendorId, [int(gameId)], [formatted_date])
        slots_by_key = {}
        for row in result:
            slot_id = int(row[0])
            slot_start = row[3]
            slot_end = row[4]
            if expected_blocks is not None and (slot_start, slot_end) not in expected_blocks:
                continue
            raw_available = int(row[2] or 0)
            booked_count = int(booking_counts.get((slot_id, formatted_date), 0))
            computed_available = max(total_slots_for_game - booked_count, 0)
            raw_available = _repair_leaked_capacity(
                vendorId, slot_id, formatted_date, raw_available,
                computed_available - int(qr_units.get((slot_id, formatted_date), 0)))
            # `available_slot` in VENDOR_<id>_SLOT is the source of truth and already
            # decremented by booking flow (including PC squad slot_units). Never inflate
            # availability above this value via booking-row count heuristics.
            resolved_available = min(raw_available, computed_available) if bool(row[1]) else 0
            resolved_available = min(resolved_available, free_console_capacity(
                live_holds, int(gameId), formatted_date, slot_start, slot_end))
            slot_is_available = resolved_available > 0

            candidate = {
                "slot_id": slot_id,
                "start_time": slot_start.strftime("%H:%M:%S"),
                "end_time": slot_end.strftime("%H:%M:%S"),
                "is_available": bool(slot_is_available),
                "available_slot": int(resolved_available),
                # The price checkout charges for this slot (offers applied);
                # base_slot_price is the console's undiscounted price.
                "single_slot_price": slot_price(int(gameId), single_slot_price, formatted_date, slot_start, slot_end),
                "base_slot_price": single_slot_price,
            }
            dedupe_key = (candidate["start_time"],)
            slots_by_key[dedupe_key] = _prefer_slot_candidate(slots_by_key.get(dedupe_key), candidate)

        slots = sorted(slots_by_key.values(), key=lambda s: s["start_time"])
        payload = {"slots": slots}
        with _slots_single_cache_lock:
            _slots_single_cache[cache_key] = {
                "payload": payload,
                "expires_at": now_ts + SLOTS_SINGLE_CACHE_TTL_SEC,
            }
        response = jsonify(payload)
        response.headers["X-Cache"] = "MISS"
        return response, 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@slot_blueprint.route('/getSlotsBatch/vendor/<int:vendorId>', methods=['POST'])
def get_slots_batch(vendorId):
    """
    Fetch slots for multiple games and dates in ONE optimized query.
    Request body: { "game_ids": [1, 2, 3], "dates": ["20260105", "20260106", "20260107"] }
    """
    started_at = time.perf_counter()
    try:
        data = request.get_json(silent=True) or {}
        game_ids = data.get('game_ids') or []
        dates = data.get('dates') or []
        
        if not game_ids or not dates:
            return jsonify({"error": "game_ids and dates are required"}), 400

        if not isinstance(game_ids, list) or not isinstance(dates, list):
            return jsonify({"error": "game_ids and dates must be arrays"}), 400

        if len(game_ids) > 32 or len(dates) > 31:
            return jsonify({"error": "Too many game_ids or dates requested"}), 400

        normalized_game_ids = []
        for game_id in game_ids:
            try:
                normalized_game_ids.append(int(game_id))
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid game_id: {game_id}"}), 400

        game_ids = sorted(set(normalized_game_ids))
        
        # Validate and format dates
        formatted_dates = []
        normalized_dates = []
        for date in dates:
            if len(date) != 8 or not date.isdigit():
                return jsonify({"error": f"Invalid date format: {date}. Use YYYYMMDD."}), 400
            normalized_dates.append(date)
            formatted_dates.append(f"{date[:4]}-{date[4:6]}-{date[6:8]}")

        normalized_dates = sorted(set(normalized_dates))
        formatted_dates = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in normalized_dates]
        for gid in game_ids:
            for date_val in formatted_dates:
                _ensure_slots_for_date(vendorId, int(gid), date_val)

        cache_key = f"vendor:{vendorId}|games:{','.join(map(str, game_ids))}|dates:{','.join(normalized_dates)}"
        now_ts = time.time()
        with _slots_batch_cache_lock:
            cached_entry = _slots_batch_cache.get(cache_key)
        if not _force_slot_refresh() and cached_entry and cached_entry["expires_at"] > now_ts:
            response = jsonify(cached_entry["payload"])
            response.headers["X-Cache"] = "HIT"
            response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
            return response, 200
        
        table_name = f"VENDOR_{vendorId}_SLOT"
        
        sql_query = text(f"""
            SELECT 
                vs.slot_id,
                vs.date,
                vs.is_available,
                vs.available_slot,
                s.start_time,
                s.end_time,
                s.gaming_type_id,
                ag.single_slot_price,
                ag.id as game_id
            FROM {table_name} vs
            INNER JOIN slots s ON s.id = vs.slot_id
            INNER JOIN available_games ag ON ag.id = s.gaming_type_id
            INNER JOIN available_game_console agc ON agc.available_game_id = ag.id
            INNER JOIN consoles c ON c.id = agc.console_id AND c.vendor_id = :vendorId
            WHERE vs.date IN :dates
              AND s.gaming_type_id IN :game_ids
              AND ag.vendor_id = :vendorId
            GROUP BY vs.slot_id, vs.date, vs.is_available, vs.available_slot, s.start_time, s.end_time, s.gaming_type_id, ag.single_slot_price, ag.id
            ORDER BY vs.date, s.start_time ASC
        """).bindparams(
            bindparam("dates", expanding=True),
            bindparam("game_ids", expanding=True),
        )
        
        result = db.session.execute(
            sql_query, 
            {
                "dates": formatted_dates,
                "game_ids": game_ids,
                "vendorId": vendorId
            }
        ).fetchall()
        
        total_slots_map = {
            int(g.id): int(g.total_slot or 0)
            for g in AvailableGame.query.filter(
                AvailableGame.id.in_(game_ids), AvailableGame.vendor_id == vendorId).all()
        }
        for gid in list(total_slots_map):
            total_slots_map[gid] = sync_game_capacity(vendorId, gid) or total_slots_map[gid]
        booking_counts = _load_booking_counts(vendorId, game_ids, formatted_dates)
        qr_units = _load_qr_held_units(vendorId, formatted_dates)
        live_holds = load_console_holds(vendorId, game_ids)
        expected_blocks_by_date = {
            d: _expected_blocks_for_date(vendorId, d) for d in formatted_dates
        }

        slots_by_date = {}
        for date in normalized_dates:
            slots_by_date[date] = []

        merged_slots_by_date = {date: {} for date in normalized_dates}
        slot_price = _slot_price_lookup(vendorId, game_ids, formatted_dates)
        
        for row in result:
            date_obj = row[1]
            date_key = date_obj.strftime("%Y%m%d")
            expected_blocks = expected_blocks_by_date.get(date_obj.strftime("%Y-%m-%d"))
            if expected_blocks is not None and (row[4], row[5]) not in expected_blocks:
                continue
            raw_available = int(row[3] or 0)
            game_id = int(row[8])
            booked_count = int(booking_counts.get((int(row[0]), date_obj.strftime("%Y-%m-%d")), 0))
            computed_available = max(int(total_slots_map.get(game_id, 0)) - booked_count, 0)
            day_key = date_obj.strftime("%Y-%m-%d")
            raw_available = _repair_leaked_capacity(
                vendorId, int(row[0]), day_key, raw_available,
                computed_available - int(qr_units.get((int(row[0]), day_key), 0)))
            # Keep DB availability authoritative; count-based estimate is only a cap.
            resolved_available = min(raw_available, computed_available) if bool(row[2]) else 0
            resolved_available = min(resolved_available, free_console_capacity(
                live_holds, game_id, date_obj, row[4], row[5]))
            slot_is_available = resolved_available > 0
            
            candidate = {
                "slot_id": int(row[0]),
                "start_time": row[4].strftime("%H:%M:%S") if hasattr(row[4], 'strftime') else str(row[4]),
                "end_time": row[5].strftime("%H:%M:%S") if hasattr(row[5], 'strftime') else str(row[5]),
                "is_available": slot_is_available,
                "available_slot": resolved_available,
                "single_slot_price": slot_price(game_id, row[7], date_obj, row[4], row[5]),
                "base_slot_price": row[7],
                "console_id": game_id
            }
            dedupe_key = (candidate["start_time"], int(candidate["console_id"]))
            merged_slots_by_date[date_key][dedupe_key] = _prefer_slot_candidate(
                merged_slots_by_date[date_key].get(dedupe_key),
                candidate,
            )

        for date_key in normalized_dates:
            slots_by_date[date_key] = sorted(
                merged_slots_by_date[date_key].values(),
                key=lambda s: (s["start_time"], int(s["console_id"])),
            )

        with _slots_batch_cache_lock:
            _slots_batch_cache[cache_key] = {
                "payload": slots_by_date,
                "expires_at": time.time() + SLOTS_BATCH_CACHE_TTL_SEC,
            }

        response = jsonify(slots_by_date)
        response.headers["X-Cache"] = "MISS"
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
        return response, 200
        
    except Exception as e:
        current_app.logger.error(f"Batch slots error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@slot_blueprint.route('/getSlotList/vendor/<int:vendor_id>/game/<int:game_id>', methods=['GET'])
def get_next_six_slot_for_game(vendor_id, game_id):
    """
    Fetches the next six available slots for a given vendor and game based on the current IST time.
    """
    try:
        current_app.logger.info("Fetching available slots for vendor_id=%s, game_id=%s", vendor_id, game_id)

        # Set current time in IST (Asia/Kolkata)
        ist = timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        current_time = now_ist.time()
        today_date = now_ist.date()

        current_app.logger.info(f"IST Time={current_time}, Date={today_date}")

        # Fetch the next 6 future slots for this game
        next_slots = db.session.query(Slot.id, Slot.start_time, Slot.end_time).filter(
            Slot.gaming_type_id == game_id,
            Slot.start_time > current_time
        ).order_by(Slot.start_time).limit(6).all()

        if not next_slots:
            return jsonify({"message": "No available slots found"}), 404

        slot_ids = [slot.id for slot in next_slots]

        # Build and execute the dynamic vendor slot availability query
        slot_query = text(f"""
            SELECT slot_id, is_available
            FROM VENDOR_{vendor_id}_SLOT
            WHERE date = :today_date
            AND slot_id IN :slot_ids
            ORDER BY slot_id;
        """)

        slot_results = db.session.execute(
            slot_query,
            {"today_date": today_date, "slot_ids": tuple(slot_ids)}
        ).fetchall()

        availability_map = {row.slot_id: row.is_available for row in slot_results}

        slots = []
        for slot in next_slots:
            slots.append({
                "slot_id": slot.id,
                "start_time": slot.start_time.strftime("%H:%M:%S"),
                "end_time": slot.end_time.strftime("%H:%M:%S"),
                "is_available": availability_map.get(slot.id, False)
            })

        return jsonify(slots), 200

    except Exception as e:
        current_app.logger.error(f"Failed to fetch slots: {str(e)}")
        return jsonify({"message": "Failed to fetch slots", "error": str(e)}), 500

def register_socketio_events(socketio):
    """
    Register WebSocket events with the given SocketIO instance.
    """
    @socketio.on('connect')
    def handle_connect():
        current_app.logger.info("Client connected")
        emit('message', {"data": "Connected to WebSocket server"})

    @socketio.on('get_slots')
    def handle_get_slots(data):
        try:
            # Query the database for slot details
            slots = Slot.query.all()
            slots_data = [slot.to_dict() for slot in slots]
            emit('slot_details', {"slots": slots_data}, broadcast=False)
        except Exception as e:
            current_app.logger.error(f"Error fetching slots: {str(e)}")
            emit('error', {"message": f"Error fetching slots: {str(e)}"})
