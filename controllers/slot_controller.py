from flask import Blueprint, jsonify, current_app, request
from models.slot import Slot
from flask_socketio import emit
from db.extensions import db
from sqlalchemy.sql import text, bindparam
from sqlalchemy import func, tuple_
from datetime import datetime, timedelta
from models.availableGame import AvailableGame
from models.availableGame import available_game_console
from models.console import Console
from models.booking import Booking
from models.transaction import Transaction
from pytz import timezone
import time
import threading


slot_blueprint = Blueprint('slots', __name__)
SLOTS_BATCH_CACHE_TTL_SEC = 5
_slots_batch_cache = {}
_slots_batch_cache_lock = threading.Lock()


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


def _ensure_slots_for_date(vendor_id, game_id, formatted_date):
    """
    Self-heal missing slots for a specific vendor/game/date based on vendor_day_slot_config.
    Keeps data consistent when historical cleanup removed some slot templates.
    """
    dt_obj = datetime.strptime(formatted_date, "%Y-%m-%d").date()
    day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt_obj.weekday()]

    cfg = db.session.execute(
        text(
            """
            SELECT day, opening_time, closing_time, slot_duration
            FROM vendor_day_slot_config
            WHERE vendor_id = :vendor_id
              AND lower(substr(day, 1, 3)) = :day_key
            LIMIT 1
            """
        ),
        {"vendor_id": vendor_id, "day_key": day_key},
    ).fetchone()
    if not cfg:
        return

    try:
        duration = int(cfg.slot_duration or 0)
    except (TypeError, ValueError):
        return
    if duration <= 0:
        return

    open_t = _parse_time_flexible(cfg.opening_time)
    close_t = _parse_time_flexible(cfg.closing_time)
    if not open_t or not close_t:
        return

    blocks = _generate_blocks(dt_obj, open_t, close_t, duration)
    if not blocks:
        return

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
            SELECT :vendor_id, :date_val::date, s_id.slot_id, TRUE, :available_slot
            FROM (SELECT unnest(:slot_ids) AS slot_id) s_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM {table_name} v
                WHERE v.vendor_id = :vendor_id
                  AND v.date = :date_val::date
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


def _load_booking_counts(vendor_id, game_ids, formatted_dates):
    """
    Return map {(slot_id, YYYY-MM-DD): count_of_active_bookings}
    for selected vendor/game/date window.
    """
    if not game_ids or not formatted_dates:
        return {}

    rows = (
        db.session.query(
            Booking.slot_id,
            Transaction.booked_date,
            func.count(Booking.id).label("cnt"),
        )
        .join(Transaction, Transaction.booking_id == Booking.id)
        .filter(
            Booking.game_id.in_(game_ids),
            Transaction.vendor_id == vendor_id,
            Transaction.booked_date.in_(formatted_dates),
            Booking.slot_id.isnot(None),
            func.lower(func.coalesce(Booking.status, "")).notin_(["cancelled", "rejected"]),
        )
        .group_by(Booking.slot_id, Transaction.booked_date)
        .all()
    )

    out = {}
    for row in rows:
        if not row.slot_id or not row.booked_date:
            continue
        out[(int(row.slot_id), row.booked_date.strftime("%Y-%m-%d"))] = int(row.cnt or 0)
    return out

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
        table_name = f"VENDOR_{vendorId}_SLOT"
        _ensure_slots_for_date(vendorId, int(gameId), formatted_date)

        # Step 1: Get price from AvailableGame and ensure real console mapping exists.
        available_game = AvailableGame.query.filter_by(id=gameId, vendor_id=vendorId).first()
        if not available_game:
            return jsonify({"error": "Game not found for this vendor."}), 404
        mapped_console_count = (
            db.session.query(func.count(func.distinct(Console.id)))
            .select_from(available_game_console)
            .join(Console, Console.id == available_game_console.c.console_id)
            .filter(
                available_game_console.c.available_game_id == gameId,
                Console.vendor_id == vendorId,
            )
            .scalar()
            or 0
        )
        if mapped_console_count <= 0:
            return jsonify({"slots": []}), 200

        single_slot_price = available_game.single_slot_price

        # Step 2: Fetch relevant slots from dynamic slot table
        sql_query = text(f"""
            SELECT slot_id, is_available, available_slot
            FROM {table_name}
            WHERE date = :date AND slot_id IN (
                SELECT id FROM slots WHERE gaming_type_id = :gameId
            )
            ORDER BY slot_id;
        """)
        result = db.session.execute(sql_query, {"date": formatted_date, "gameId": gameId}).fetchall()

        slot_ids = [int(row[0]) for row in result]
        slot_rows = []
        if slot_ids:
            slot_rows = (
                Slot.query
                .filter(Slot.id.in_(slot_ids), Slot.gaming_type_id == gameId)
                .order_by(Slot.start_time.asc())
                .all()
            )
        vendor_slot_map = {int(row[0]): {"is_available": bool(row[1]), "available_slot": int(row[2] or 0)} for row in result}

        day_duration_map = _load_vendor_day_duration_map(vendorId)
        total_slots_map = {
            int(g.id): int(g.total_slot or 0)
            for g in AvailableGame.query.filter(AvailableGame.id.in_(game_ids)).all()
        }
        booking_counts = _load_booking_counts(vendorId, game_ids, formatted_dates)
        total_slots_for_game = int(available_game.total_slot or 0)
        booking_counts = _load_booking_counts(vendorId, [int(gameId)], [formatted_date])
        weekday_key = _weekday_key_from_yyyymmdd(date)
        expected_duration = day_duration_map.get(weekday_key)

        slots_by_key = {}
        for slot in slot_rows:
            slot_duration = _slot_duration_minutes(slot.start_time, slot.end_time)
            if expected_duration and slot_duration != expected_duration:
                continue
            vendor_entry = vendor_slot_map.get(int(slot.id))
            if vendor_entry:
                raw_available = int(vendor_entry.get("available_slot") or 0)
                booked_count = int(booking_counts.get((int(slot.id), formatted_date), 0))
                computed_available = max(total_slots_for_game - booked_count, 0)
                resolved_available = max(raw_available, computed_available)
                slot_is_available = resolved_available > 0
            else:
                continue

            candidate = {
                "slot_id": int(slot.id),
                "start_time": slot.start_time.strftime("%H:%M:%S"),
                "end_time": slot.end_time.strftime("%H:%M:%S"),
                "is_available": bool(slot_is_available),
                "available_slot": int(resolved_available),
                "single_slot_price": single_slot_price
            }
            dedupe_key = (candidate["start_time"],)
            slots_by_key[dedupe_key] = _prefer_slot_candidate(slots_by_key.get(dedupe_key), candidate)

        slots = sorted(slots_by_key.values(), key=lambda s: s["start_time"])
        return jsonify({"slots": slots}), 200

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
        if cached_entry and cached_entry["expires_at"] > now_ts:
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
        
        day_duration_map = _load_vendor_day_duration_map(vendorId)

        slots_by_date = {}
        for date in normalized_dates:
            slots_by_date[date] = []

        merged_slots_by_date = {date: {} for date in normalized_dates}
        
        for row in result:
            date_obj = row[1]
            date_key = date_obj.strftime("%Y%m%d")
            weekday_key = _weekday_key_from_yyyymmdd(date_key)
            expected_duration = day_duration_map.get(weekday_key)
            actual_duration = _slot_duration_minutes(row[4], row[5])
            if expected_duration and actual_duration != expected_duration:
                continue
            raw_available = int(row[3] or 0)
            game_id = int(row[8])
            booked_count = int(booking_counts.get((int(row[0]), date_obj.strftime("%Y-%m-%d")), 0))
            computed_available = max(int(total_slots_map.get(game_id, 0)) - booked_count, 0)
            resolved_available = max(raw_available, computed_available)
            slot_is_available = resolved_available > 0
            
            candidate = {
                "slot_id": int(row[0]),
                "start_time": row[4].strftime("%H:%M:%S") if hasattr(row[4], 'strftime') else str(row[4]),
                "end_time": row[5].strftime("%H:%M:%S") if hasattr(row[5], 'strftime') else str(row[5]),
                "is_available": slot_is_available,
                "available_slot": resolved_available,
                "single_slot_price": row[7],
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
