"""Pure flex-start rules: no database, no Flask app."""
import importlib.util
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flex_timing_under_test", ROOT / "services/flex_timing.py")
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)

D = date(2026, 11, 26)
ON = dict(ft.DEFAULT_SETTINGS, flex_enabled=True)


def hourly(day=D, first=10, last=23, available=3, full=()):
    """One-hour slots first:00..last:00 on ``day``; ids are the hour (+100 per later day)."""
    offset = (day - D).days * 100
    return [ft.occurrence(day, offset + h, time(h), time((h + 1) % 24), 0 if h in full else available, h not in full)
            for h in range(first, last + 1)]


def at(h, m=0, day=D):
    return datetime.combine(day, time(h, m))


# Scenario 1: walk-in 10:12 for 2h -> 10:12-12:12 consuming 10, 11 and 12.
def test_walk_in_window_consumes_every_overlapped_slot():
    plan = ft.build_plan(hourly(), at(10, 12), 120, ON, now=at(10, 12))
    assert (plan.start, plan.end) == (at(10, 12), at(12, 12))
    assert [o.slot_id for o in plan.consumed] == [10, 11, 12]
    assert plan.base.slot_id == 10 and [o.slot_id for o in plan.extra] == [11, 12]


def test_half_open_intervals_back_to_back_never_conflict():
    # Scenario 3 (rule level): 10:12-12:12 then 12:12-13:00 on one station.
    assert not ft.overlaps(at(10, 12), at(12, 12), at(12, 12), at(13))
    assert ft.overlaps(at(10, 12), at(12, 12), at(12, 11), at(13))
    plan = ft.build_plan(hourly(), at(12, 12), 48, ON, now=at(10))
    assert [o.slot_id for o in plan.consumed] == [12]
    assert ft.max_free_minutes(at(12, 12), [(at(10, 12), at(12, 12))]) == ft.MAX_MINUTES


# Scenario 2: station has an app/desk booking at 12:00 -> offer 108 minutes.
def test_station_with_later_booking_offers_shorter_window():
    plan = ft.build_plan(hourly(), at(10, 12), 120, ON, now=at(10, 12))
    rows = [{"book_status": "upcoming", "date": D, "start_time": time(12), "end_time": time(13)}]
    busy = {1: ft.busy_intervals(rows, at(10, 12)), 2: []}
    stations = ft.evaluate_consoles([{"id": 1, "name": "PC 1"}, {"id": 2, "name": "PC 2"}], busy, plan)
    assert stations[0]["available"] is False and stations[0]["max_minutes_available"] == 108
    assert stations[0]["next_busy_at"].startswith("2026-11-26T12:00:00+05:30")
    assert stations[1]["available"] is True


def test_live_session_blocks_through_overtime_hold():
    rows = [{"book_status": "current", "date": D, "start_time": time(9), "end_time": time(10)}]
    busy = ft.busy_intervals(rows, at(10, 12))
    assert busy == [(at(9), at(11))]  # 10:00 floor + 1h overtime hold
    assert ft.max_free_minutes(at(10, 12), busy) == 0


# Scenario 4: slot capacity (unassigned app bookings) limits the window.
def test_full_slot_limits_window_with_max_minutes():
    with pytest.raises(ft.FlexError) as err:
        ft.build_plan(hourly(full={12}), at(10, 12), 120, ON, now=at(10, 12))
    assert err.value.code == "slot_full" and err.value.details["max_minutes"] == 108


def test_squad_units_need_room_in_every_slot():
    occs = hourly(available=1)
    with pytest.raises(ft.FlexError) as err:
        ft.build_plan(occs, at(10, 12), 60, ON, units=2, now=at(10))
    assert err.value.details["max_minutes"] == 0
    assert ft.build_plan(occs, at(10, 12), 60, ON, units=1, now=at(10)).consumed


# Scenario 9: overnight and closing time.
def test_overnight_window_spans_two_dates_on_24h_grid():
    occs = hourly(first=0, last=23) + hourly(D + timedelta(days=1), first=0, last=23)
    plan = ft.build_plan(occs, at(23, 30), 120, ON, now=at(23, 30))
    assert plan.end == at(1, 30, D + timedelta(days=1))
    assert [(o.day, o.start.hour) for o in plan.consumed] == [
        (D, 23), (D + timedelta(days=1), 0), (D + timedelta(days=1), 1)]
    assert plan.base.day == D


def test_closing_time_rejects_and_offers_until_close():
    with pytest.raises(ft.FlexError) as err:
        ft.build_plan(hourly(last=22), at(22, 30), 60, ON, now=at(22, 30))  # closes 23:00
    assert err.value.code == "too_long" and err.value.details["max_minutes"] == 30
    assert err.value.details["limit_reason"] == "closing"


def test_allow_past_closing_only_consumes_existing_slots():
    plan = ft.build_plan(hourly(last=22), at(22, 30), 60, dict(ON, allow_past_closing=True), now=at(22, 30))
    assert [o.slot_id for o in plan.consumed] == [22]
    with pytest.raises(ft.FlexError) as err:
        ft.build_plan(hourly(last=22), at(23, 30), 60, ON, now=at(23))
    assert err.value.code == "closed"


def test_base_slot_is_dated_on_the_window_start():
    # A 23:30-00:30 slot belongs to the 26th; a 00:10 start on the 27th uses the 27th's 00:30 slot.
    next_day = D + timedelta(days=1)
    occs = [ft.occurrence(D, 1, time(23, 30), time(0, 30), 2), ft.occurrence(next_day, 2, time(0, 30), time(1, 30), 2)]
    plan = ft.build_plan(occs, at(0, 10, next_day), 60, ON, now=at(0, 10, next_day))
    assert plan.base.slot_id == 2 and [o.slot_id for o in plan.extra] == [1]
    with pytest.raises(ft.FlexError):
        ft.build_plan(occs, at(0, 10, next_day), 15, dict(ON, min_minutes=5), now=at(0, 10, next_day))


# Scenario 11: timezone handling.
def test_start_parsing_is_ist_and_minute_precise():
    assert ft.to_ist_naive("2026-11-26T04:42:30Z") == at(10, 12)
    assert ft.to_ist_naive("2026-11-26T10:12:59+05:30") == at(10, 12)
    assert ft.to_ist_naive("2026-11-26T10:12") == at(10, 12)
    now = datetime(2026, 11, 26, 4, 42, tzinfo=timezone.utc)
    assert ft.to_ist_naive("now", now) == at(10, 12)
    assert ft.iso(at(10, 12)) == "2026-11-26T10:12:00+05:30"
    with pytest.raises(ft.FlexError):
        ft.to_ist_naive("tomorrow")


def test_start_in_past_and_finished_windows_are_refused():
    with pytest.raises(ft.FlexError) as err:
        ft.build_plan(hourly(), at(10), 60, ON, now=at(10, 31))
    assert err.value.code == "start_in_past"
    assert ft.build_plan(hourly(), at(10, 12), 60, ON, now=at(10, 30)).start == at(10, 12)


# Pricing fallback.
def test_fallback_price_prorates_in_steps_and_caps_at_whole_slots():
    assert ft.fallback_price(120, 100, 60, 15) == Decimal("200.00")
    assert ft.fallback_price(108, 100, 60, 15) == Decimal("200.00")   # billed 120 min, cap 2 slots
    assert ft.fallback_price(50, 100, 60, 15) == Decimal("100.00")    # billed 60
    assert ft.fallback_price(40, 99, 60, 15) == Decimal("75.00")      # 99*45/60 = 74.25 -> 75
    assert ft.fallback_price(70, 100, 60, 15) == Decimal("125.00")
    assert ft.fallback_price(30, 0, 60, 15) == Decimal("0.00")


def test_marginal_extension_price_never_double_charges():
    # Scenario 5 pricing rule: price(prev+extra) - price(prev).
    # 2h booked + 48 min: billed 180 total (15-min steps) minus the 120 already paid.
    assert ft.fallback_price(168, 100, 60, 15) - ft.fallback_price(120, 100, 60, 15) == Decimal("100.00")
    # 10:12 walk-in of 60 min extended by 30 min: 90 - 60 billed minutes.
    assert ft.fallback_price(90, 100, 60, 15) - ft.fallback_price(60, 100, 60, 15) == Decimal("50.00")


# Scenarios 7 and 8: late and early arrival.
def test_late_arrival_policies():
    assert ft.arrival_window(at(11), at(12), at(11, 20), "keep_end") == (at(11, 20), at(12))
    assert ft.arrival_window(at(11), at(12), at(11, 20), "shift_if_free") == (at(11, 20), at(12, 20))
    with pytest.raises(ft.FlexError):
        ft.arrival_window(at(11), at(12), at(12), "keep_end")


def test_early_arrival_keeps_duration():
    start, end = ft.arrival_window(at(11), at(12), at(10, 45), "keep_end")
    assert (start, end) == (at(10, 45), at(11, 45))
    consumed = ft.overlapped(hourly(), start, end)
    assert [o.slot_id for o in ft.newly_needed({(D, 11)}, consumed)] == [10]


# Scenario 6: early end / shorten.
def test_shorten_releases_only_untouched_slots():
    held = [o for o in hourly() if o.slot_id in (10, 11, 12)]
    assert [o.slot_id for o in ft.released_after(held, at(11, 5))] == [12]
    assert [o.slot_id for o in ft.released_after(held, at(11))] == [11, 12]


def test_partial_slot_grace_only_when_another_station_is_free():
    settings = dict(ON, partial_slot_grace_minutes=5)
    plan = ft.build_plan(hourly(available=2), at(10, 12), 113, settings, now=at(10))  # ends 12:05
    assert [o.slot_id for o in plan.consumed] == [10, 11]
    plan = ft.build_plan(hourly(available=1), at(10, 12), 113, settings, now=at(10))
    assert [o.slot_id for o in plan.consumed] == [10, 11, 12]


def test_settings_validation():
    merged = ft.normalize_settings({"flex_enabled": True, "step_minutes": 5}, ft.DEFAULT_SETTINGS)
    assert merged["flex_enabled"] and merged["step_minutes"] == 5 and merged["min_minutes"] == 30
    for bad in ({"flex_enabled": "yes"}, {"step_minutes": 0}, {"late_arrival_policy": "drop"},
                {"partial_slot_grace_minutes": 40}, {"min_minutes": 10, "partial_slot_grace_minutes": 10}):
        with pytest.raises(ft.FlexError):
            ft.normalize_settings(bad)
    assert ft.validate_duration(108, ON) == 108
    with pytest.raises(ft.FlexError):
        ft.validate_duration(20, ON)


def test_schedule_close_follows_contiguous_grid():
    assert ft.schedule_close(hourly(last=22), at(10, 12)) == at(23)
    gap = [o for o in hourly() if o.slot_id != 15]
    assert ft.schedule_close(gap, at(10, 12)) == at(15)
    assert ft.schedule_close(hourly(), at(9)) is None
