# utils/realtime.py
from __future__ import annotations
from datetime import datetime, date, time
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

# Optional: allow consumer to pass a formatter, else fallback to 12h
def _fmt_time(t: TimeLike, fmt: str = "%I:%M %p") -> str:
    if isinstance(t, (datetime, time)):
        return t.strftime(fmt)
    # If already a serialized string, trust producer (ensure it's safe upstream)
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

def _canonical_payload(data: Dict[str, Any], time_fmt: str) -> Dict[str, Any]:
    # Ingest legacy keys
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

    # status fields
    machine_status = _coalesce(data.get("status"), "pending_verified")
    booking_status = _coalesce(data.get("booking_status"), data.get("book_status"))

    # normalize times
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
    # Filter out None and extraneous keys
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
    """
    Production-ready emitter for booking-related events.

    - Ensures canonical payload
    - Adds event metadata (event_id, emitted_at)
    - Emits to vendor room by default if vendor_id provided
    - Returns event_id for idempotency tracking upstream

    This function is tolerant to Flask-SocketIO/python-socketio API differences by
    using 'to=' (newer) or 'room=' (older) parameter names when emitting.
    """
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

        # Final allowlist filter + include metadata
        filtered_payload = {k: v for k, v in full_payload.items() if k in CANONICAL_KEYS}
        filtered_payload["event_id"] = full_payload["event_id"]
        filtered_payload["emitted_at"] = full_payload["emitted_at"]

        # Prepare emit kwargs in a version-compatible way:
        # - Newer python-socketio prefers 'to='
        # - Older Flask-SocketIO accepted 'room='
        emit_kwargs = {"namespace": namespace} if namespace else {}

        # Try 'to' first, fall back to 'room'
        try:
            if target_room:
                socketio.emit(event, filtered_payload, to=target_room, **emit_kwargs)
            else:
                socketio.emit(event, filtered_payload, **emit_kwargs)
        except TypeError:
            # Older API path: use 'room='
            if target_room:
                socketio.emit(event, filtered_payload, room=target_room, **emit_kwargs)
            else:
                socketio.emit(event, filtered_payload, **emit_kwargs)

        logger.info(
            "emit_booking_event: event='%s' vendor=%s room=%s payload_keys=%s",
            event, vendor_id, target_room, list(filtered_payload.keys())
        )
        return eid

    except Exception as exc:
        logger.exception("emit_booking_event failed: event='%s' error=%s", event, exc)
        return None
