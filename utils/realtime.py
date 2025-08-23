# utils/realtime.py
from __future__ import annotations
from datetime import datetime, date, time
from decimal import Decimal
from typing import Any, Dict, Optional, List, Union
import logging
import uuid

logger = logging.getLogger(__name__)

TimeLike = Union[datetime, time, str]
BlockLike = Union[str, List[Dict[str, TimeLike]]]

CANONICAL_KEYS = {
    "event_id", "emitted_at",
    "bookingId", "slotId", "vendorId",
    "userId", "username",
    "game", "game_id",
    "consoleType", "consoleNumber",
    "date", "slot_price",
    "status", "statusLabel", "booking_status",
    "time", "processed_time",
}

def _fmt_time(t: TimeLike, fmt: str = "%I:%M %p") -> str:
    if isinstance(t, (datetime, time)):
        return t.strftime(fmt)
    return str(t)

def _normalize_block(block: Optional[BlockLike], fmt: str = "%I:%M %p") -> Optional[str]:
    if not block:
        return None
    if isinstance(block, str):
        return block
    if isinstance(block, list) and block:
        first = block[0]
        st = _fmt_time(first.get("start_time"), fmt) if first.get("start_time") is not None else None
        et = _fmt_time(first.get("end_time"), fmt) if first.get("end_time") is not None else None
        if st and et:
            return f"{st} - {et}"
    return None

def _coalesce(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

def _as_date_str(d: Union[date, datetime, str, None]) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)

def _derive_status_label(machine_status: str) -> str:
    return "Pending" if machine_status in ("pending_verified", "pending_acceptance") else "Confirmed"

def _as_mapping(obj: Any) -> Optional[Dict[str, Any]]:
    # SQLAlchemy Row/RowMapping compatibility
    try:
        # Row has _mapping attr that is a read-only mapping
        mp = getattr(obj, "_mapping", None)
        if mp is not None:
            return dict(mp)
    except Exception:
        pass
    # RowProxy/legacy rows behave like sequences with keys(); try dict() directly
    try:
        if hasattr(obj, "keys"):
            return dict(obj)
    except Exception:
        pass
    return None

def _to_jsonable(obj: Any) -> Any:
    # Fast path for primitives
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # Datetime/date/time
    if isinstance(obj, datetime):
        return obj.isoformat() + ("Z" if obj.tzinfo is None else "")
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.strftime("%H:%M:%S")

    # Decimal
    if isinstance(obj, Decimal):
        # Choose float; if precision matters, use str(obj)
        return float(obj)

    # SQLAlchemy Row/RowMapping or similar mappings
    mp = _as_mapping(obj)
    if mp is not None:
        return {k: _to_jsonable(v) for k, v in mp.items()}

    # dict
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    # list/tuple/set
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]

    # Objects with __dict__
    if hasattr(obj, "__dict__"):
        try:
            return {k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
        except Exception:
            pass

    # Fallback to string representation
    return str(obj)

def _canonical_payload(data: Dict[str, Any], time_fmt: str) -> Dict[str, Any]:
    username = _coalesce(data.get("username"), data.get("user_name"))
    booking_id = _coalesce(data.get("bookingId"), data.get("booking_id"))
    slot_id = _coalesce(data.get("slotId"), data.get("slot_id"))
    vendor_id = _coalesce(data.get("vendorId"), data.get("vendor_id"))
    user_id = _coalesce(data.get("userId"), data.get("user_id"))
    game = _coalesce(data.get("game"), data.get("game_name"))
    game_id = data.get("game_id")
    console_type = data.get("consoleType")
    console_number = data.get("consoleNumber")
    date_val = _as_date_str(data.get("date"))
    slot_price = data.get("slot_price")

    machine_status = _coalesce(data.get("status"), "pending_verified")
    booking_status = _coalesce(data.get("booking_status"), data.get("book_status"))

    time_block = _normalize_block(data.get("time"), time_fmt)
    processed_block = _normalize_block(data.get("processed_time"), time_fmt)

    payload = {
        "bookingId": booking_id,
        "slotId": slot_id,
        "vendorId": vendor_id,
        "userId": user_id,
        "username": username,
        "game": game,
        "game_id": game_id,
        "consoleType": console_type,
        "consoleNumber": console_number,
        "date": date_val,
        "slot_price": slot_price,
        "status": machine_status,
        "statusLabel": _derive_status_label(machine_status),
        "booking_status": booking_status,
        "time": time_block,
        "processed_time": processed_block,
    }
    return {k: v for k, v in payload.items() if v is not None}

def emit_booking_event(
    socketio: Any,
    event: str,
    data: Dict[str, Any],
    *,
    vendor_id: Optional[int] = None,
    room: Optional[str] = None,
    namespace: Optional[str] = None,
    time_fmt: str = "%I:%M %p",
    event_id: Optional[str] = None
) -> Optional[str]:
    if not socketio:
        logger.warning("emit_booking_event: SocketIO unavailable; event='%s'", event)
        return None

    try:
        payload = _canonical_payload(data, time_fmt)
        if not payload.get("bookingId") and event != "dashboard_refreshed":
            logger.warning("emit_booking_event: missing bookingId for event='%s'; payload=%s", event, payload)

        eid = event_id or str(uuid.uuid4())
        meta = {
            "event_id": eid,
            "emitted_at": datetime.utcnow().isoformat() + "Z",
        }
        full_payload = {**meta, **payload}

        target_room = room or (f"vendor_{vendor_id}" if vendor_id else None)

        # Allowlist + metadata
        filtered_payload = {k: v for k, v in full_payload.items() if k in CANONICAL_KEYS}
        filtered_payload["event_id"] = full_payload["event_id"]
        filtered_payload["emitted_at"] = full_payload["emitted_at"]

        # FINAL: Make sure it's JSON-serializable
        serializable_payload = _to_jsonable(filtered_payload)

        emit_kwargs = {"namespace": namespace} if namespace else {}

        # Try 'to=' first, fallback to 'room=' on older versions
        try:
            if target_room:
                socketio.emit(event, serializable_payload, to=target_room, **emit_kwargs)
            else:
                socketio.emit(event, serializable_payload, **emit_kwargs)
        except TypeError:
            if target_room:
                socketio.emit(event, serializable_payload, room=target_room, **emit_kwargs)
            else:
                socketio.emit(event, serializable_payload, **emit_kwargs)

        logger.info(
            "emit_booking_event: event='%s' vendor=%s room=%s payload_keys=%s",
            event, vendor_id, target_room, list(serializable_payload.keys())
        )
        return eid

    except Exception as exc:
        logger.exception("emit_booking_event failed: event='%s' error=%s", event, exc)
        return None

def build_booking_event_payload(*, vendor_id, booking_id, slot_id, user_id, username,
                                game_id, game_name, date_value, slot_price,
                                start_time, end_time, console_id,
                                status: str, booking_status: str):
    # status: 'pending_verified' | 'pending_acceptance' | 'confirmed' | ...
    # booking_status: 'upcoming' | 'current' | 'past'
    payload = {
        "vendor_id": vendor_id,
        "booking_id": booking_id,
        "slot_id": slot_id,
        "user_id": user_id,
        "username": username,
        "game_id": game_id,
        "game": game_name,
        "consoleType": f"Console-{console_id}" if console_id is not None else None,
        "consoleNumber": str(console_id) if console_id is not None else None,
        "date": date_value,                 # YYYY-MM-DD or date object (emitter converts)
        "slot_price": float(slot_price) if slot_price is not None else None,
        "time": [{"start_time": start_time, "end_time": end_time}],
        "processed_time": [{"start_time": start_time, "end_time": end_time}],
        "status": status,                   # machine status
        "booking_status": booking_status,   # stage dimension per your UI contract
    }
    # Remove Nones to keep payload tight; emitter also filters
    return {k: v for k, v in payload.items() if v is not None}
