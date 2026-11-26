"""Pure rules for flex-start ("any minute") bookings.

No database or Flask imports: every rule here is unit-testable on its own.
All datetimes are naive IST wall-clock values; callers convert aware values
with ``to_ist_naive`` first. Intervals are half-open ``[start, end)`` so a
booking ending at 12:00 never conflicts with one starting at 12:00.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from math import ceil
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
LATE_POLICIES = ("keep_end", "shift_if_free")
DEFAULT_SETTINGS = {
    "flex_enabled": False,
    "min_minutes": 30,
    "step_minutes": 15,
    "late_arrival_policy": "keep_end",
    "allow_past_closing": False,
    "partial_slot_grace_minutes": 0,
}
MAX_MINUTES = 12 * 60
# A desk can record a walk-in a little after they sat down (10:12 entered at 10:20).
PAST_START_GRACE = timedelta(minutes=30)


class FlexError(ValueError):
    """A user-facing refusal. ``status`` maps to the HTTP code, ``details`` to extra JSON."""

    def __init__(self, message, status=409, code="flex_unavailable", **details):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


def _whole(value, low, high, label):
    if isinstance(value, bool):
        raise FlexError(f"{label} must be a whole number.", 400, "invalid_settings")
    try:
        number = int(value)
        if Decimal(str(value)) != number:
            raise ValueError
    except (TypeError, ValueError, ArithmeticError):
        raise FlexError(f"{label} must be a whole number.", 400, "invalid_settings")
    if not low <= number <= high:
        raise FlexError(f"{label} must be between {low} and {high}.", 400, "invalid_settings")
    return number


def normalize_settings(raw, current=None):
    """Merge a partial update over current settings and validate the result."""
    if not isinstance(raw, dict):
        raise FlexError("Send the flex booking settings as an object.", 400, "invalid_settings")
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in (current or {}).items() if k in DEFAULT_SETTINGS})
    merged.update({k: v for k, v in raw.items() if k in DEFAULT_SETTINGS})
    for key in ("flex_enabled", "allow_past_closing"):
        if not isinstance(merged[key], bool):
            raise FlexError(f"{key.replace('_', ' ')} must be true or false.", 400, "invalid_settings")
    merged["step_minutes"] = _whole(merged["step_minutes"], 1, 60, "Step minutes")
    merged["min_minutes"] = _whole(merged["min_minutes"], 5, MAX_MINUTES, "Minimum minutes")
    merged["partial_slot_grace_minutes"] = _whole(merged["partial_slot_grace_minutes"], 0, 30, "Partial slot grace")
    if merged["partial_slot_grace_minutes"] >= merged["min_minutes"]:
        raise FlexError("Partial slot grace must be shorter than the minimum session.", 400, "invalid_settings")
    if merged["late_arrival_policy"] not in LATE_POLICIES:
        raise FlexError("Late arrival policy must be keep_end or shift_if_free.", 400, "invalid_settings")
    return merged


def to_ist_naive(value, now=None):
    """Parse 'now', an ISO string or a datetime into naive IST, truncated to the minute.

    Aware values are converted to IST; naive values are already IST wall-clock.
    """
    if value is None or value == "" or (isinstance(value, str) and value.strip().lower() == "now"):
        moment = now or datetime.now(IST)
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise FlexError("startAt must be an ISO date-time such as 2026-11-26T10:12:00+05:30.", 400, "invalid_start")
    else:
        raise FlexError("startAt must be an ISO date-time.", 400, "invalid_start")
    if moment.tzinfo is not None:
        moment = moment.astimezone(IST).replace(tzinfo=None)
    return moment.replace(second=0, microsecond=0)


def validate_duration(minutes, settings):
    minutes = _whole(minutes, 1, MAX_MINUTES, "Duration")
    if minutes < settings["min_minutes"]:
        raise FlexError(f"Sessions start at {settings['min_minutes']} minutes.", 400, "too_short",
                        min_minutes=settings["min_minutes"])
    return minutes


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


@dataclass(frozen=True)
class SlotOccurrence:
    day: date
    slot_id: int
    start: datetime
    end: datetime
    available: int = 0
    is_available: bool = True

    def key(self):
        return (self.day, self.slot_id)


def slot_window(day, start_time, end_time):
    start = datetime.combine(day, start_time)
    end = datetime.combine(day, end_time)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def occurrence(day, slot_id, start_time, end_time, available=0, is_available=True):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    if isinstance(start_time, str):
        start_time = time.fromisoformat(start_time)
    if isinstance(end_time, str):
        end_time = time.fromisoformat(end_time)
    start, end = slot_window(day, start_time, end_time)
    return SlotOccurrence(day, int(slot_id), start, end, int(available or 0), bool(is_available))


def overlapped(occurrences, start, end, grace_minutes=0, units=1):
    """Dated slots a window consumes, chronologically.

    With a grace of N minutes, an edge slot overlapped by N minutes or less is
    not consumed, but only while the slot keeps at least one more free station
    than this booking needs (otherwise the overlap would oversell it).
    """
    hits = sorted((o for o in occurrences if overlaps(o.start, o.end, start, end)),
                  key=lambda o: (o.start, o.slot_id))
    if not grace_minutes or len(hits) < 2:
        return hits
    kept = []
    for index, item in enumerate(hits):
        edge = index in (0, len(hits) - 1)
        used = minutes_between(max(item.start, start), min(item.end, end))
        if edge and used <= grace_minutes and item.available >= units + 1:
            continue
        kept.append(item)
    return kept or hits


def choose_base(consumed, start):
    """The slot the booking row points at (legacy clients read slot_id + booked date).

    It must be dated on the window's start date so every reader that keys
    capacity by (dashboard date, booking.slot_id) releases the right row.
    """
    for item in consumed:
        if item.day == start.date():
            return item
    raise FlexError("This start time sits inside a slot from the previous day. Start on the next slot boundary.",
                    409, "no_base_slot")


def schedule_close(occurrences, start):
    """End of the contiguous slot grid that contains ``start`` (None if closed then).

    The cafe's own slot grid is its opening hours: a 24h cafe has one chain
    across midnight; a cafe closing at 23:00 has no slot after 23:00.
    """
    ordered = sorted(occurrences, key=lambda o: (o.start, o.end))
    cursor = None
    for item in ordered:
        if cursor is None:
            if item.start <= start < item.end:
                cursor = item.end
            continue
        if item.start <= cursor:
            cursor = max(cursor, item.end)
        else:
            break
    return cursor


def capacity_limit(consumed_candidates, start, units):
    """First slot (from start) without room for ``units`` limits the window to its start."""
    for item in sorted(consumed_candidates, key=lambda o: o.start):
        if not item.is_available or item.available < units:
            return max(item.start, start)
    return None


def max_free_minutes(start, busy, hard_limit=None):
    """Minutes from start until the first conflicting interval or the hard limit."""
    limit = hard_limit
    for left, right in busy:
        if left <= start < right:
            return 0
        if left >= start and (limit is None or left < limit):
            limit = left
    if limit is None:
        return MAX_MINUTES
    return max(0, min(MAX_MINUTES, minutes_between(start, limit)))


def overtime_end(now):
    """Same near-term hold as live_slot_capacity: a live session may run over."""
    return now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0) + timedelta(hours=1)


def busy_intervals(rows, now):
    """Turn dashboard rows {status,date,start_time,end_time} into busy intervals."""
    result = []
    for row in rows:
        status = str(row.get("book_status") or "").lower()
        if status not in ("current", "upcoming"):
            continue
        if row.get("start_at") is not None and row.get("end_at") is not None:
            left, right = row["start_at"], row["end_at"]
        else:
            left, right = slot_window(row["date"], row["start_time"], row["end_time"])
        if status == "current":
            right = max(right, overtime_end(now))
        result.append((left, right))
    return sorted(result)


def round_up_to_step(minutes, step):
    return int(ceil(minutes / step) * step)


def fallback_price(minutes, slot_price, slot_minutes, step_minutes):
    """Per-slot price prorated per minute, billed in step increments, rounded up to the rupee.

    Never exceeds the price of the whole slots the duration would otherwise need.
    """
    slot_price = Decimal(str(slot_price or 0))
    if slot_price <= 0:
        return Decimal("0.00")
    slot_minutes = max(1, int(slot_minutes))
    billed = round_up_to_step(minutes, step_minutes)
    amount = (slot_price * billed / slot_minutes).to_integral_value(rounding=ROUND_CEILING)
    cap = slot_price * ceil(minutes / slot_minutes)
    return min(amount, cap).quantize(Decimal("0.01"))


def typical_slot_minutes(occurrences):
    counts = {}
    for item in occurrences:
        span = minutes_between(item.start, item.end)
        if 0 < span <= 720:
            counts[span] = counts.get(span, 0) + 1
    if not counts:
        return 60
    return max(counts, key=lambda span: (counts[span], -span))


def arrival_window(booked_start, booked_end, arrived_at, policy):
    """New window for a booked slot when the gamer arrives early or late.

    early: start when they arrive, keep the booked duration.
    late, keep_end: start now, end at the booked end (same price).
    late, shift_if_free: start now, keep the booked duration (caller checks the station).
    """
    if arrived_at >= booked_end:
        raise FlexError("The booked time has already ended.", 409, "booking_ended")
    duration = booked_end - booked_start
    if arrived_at <= booked_start:
        return arrived_at, arrived_at + duration
    if policy == "shift_if_free":
        return arrived_at, arrived_at + duration
    if policy == "keep_end":
        return arrived_at, booked_end
    raise FlexError("Late arrival policy must be keep_end or shift_if_free.", 400, "invalid_policy")


def released_after(held, new_end):
    """Held slots that start at or after a new (earlier) end; a partly used slot stays consumed."""
    return [item for item in held if item.start >= new_end]


def newly_needed(held_keys, wanted):
    return [item for item in wanted if item.key() not in set(held_keys)]


def iso(value):
    """ISO string with the IST offset for a naive IST datetime."""
    return value.replace(tzinfo=IST).isoformat() if value is not None else None


def clock(value):
    return value.strftime("%H:%M")


@dataclass
class Plan:
    start: datetime
    end: datetime
    minutes: int
    consumed: list
    base: SlotOccurrence
    close: datetime = None
    limit: datetime = None
    limit_reason: str = None

    @property
    def extra(self):
        return [item for item in self.consumed if item.key() != self.base.key()]

    def slot_payload(self):
        return [{"slot_id": o.slot_id, "date": o.day.isoformat(), "start_time": clock(o.start),
                 "end_time": clock(o.end), "available_slot": o.available} for o in self.consumed]


def build_plan(occurrences, start, minutes, settings, units=1, now=None):
    """Validate a window against the schedule and slot capacity (not stations).

    Raises FlexError with ``max_minutes`` when a shorter session would fit.
    """
    now = now or datetime.now(IST).replace(tzinfo=None)
    if start < now - PAST_START_GRACE:
        raise FlexError("Start time is too far in the past. Use the current time.", 400, "start_in_past")
    end = start + timedelta(minutes=minutes)
    if end <= now:
        raise FlexError("This window has already ended.", 400, "window_ended")
    close = schedule_close(occurrences, start)
    if close is None and not settings["allow_past_closing"]:
        raise FlexError("The cafe has no slots at this start time (closed).", 409, "closed")
    limits = []
    if close is not None and not settings["allow_past_closing"]:
        limits.append((close, "closing"))
    candidates = [o for o in occurrences if overlaps(o.start, o.end, start, end)]
    cap = capacity_limit(candidates, start, units)
    if cap is not None:
        limits.append((cap, "capacity"))
    limit, reason = (min(limits) if limits else (None, None))
    if limit is not None and limit < end:
        available = max(0, minutes_between(start, limit))
        label = "closing time" if reason == "closing" else "a fully booked slot"
        raise FlexError(f"Only {available} minutes fit before {label} at {clock(limit)}.", 409,
                        "too_long" if reason == "closing" else "slot_full",
                        max_minutes=available, limit_at=iso(limit), limit_reason=reason)
    consumed = overlapped(occurrences, start, end, settings["partial_slot_grace_minutes"], units)
    if not consumed:
        if not settings["allow_past_closing"]:
            raise FlexError("No cafe slots cover this window.", 409, "closed")
        raise FlexError("At least part of the session must fall inside a cafe slot.", 409, "closed")
    base = choose_base(consumed, start)
    return Plan(start=start, end=end, minutes=minutes, consumed=consumed, base=base,
                close=close, limit=limit, limit_reason=reason)


def evaluate_consoles(consoles, busy_by_console, plan):
    """Per-station availability and the longest session each could take from plan.start."""
    result = []
    hard = plan.limit
    for console in consoles:
        busy = busy_by_console.get(console["id"], [])
        conflict = next(((l, r) for l, r in busy if overlaps(l, r, plan.start, plan.end)), None)
        longest = max_free_minutes(plan.start, busy, hard)
        result.append({
            "console_id": console["id"],
            "name": console.get("name"),
            "available": conflict is None,
            "max_minutes_available": longest,
            "next_busy_at": iso(conflict[0]) if conflict else None,
        })
    return result
