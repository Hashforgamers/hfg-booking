"""Time-bounded live holds must not hide later booking availability."""
import ast
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

source = Path(__file__).resolve().parents[1] / 'services/live_slot_capacity.py'
node = next(n for n in ast.parse(source.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'free_console_capacity')
scope = dict(datetime=datetime, timedelta=timedelta, ZoneInfo=ZoneInfo)
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
capacity = scope['free_console_capacity']


def holds(status='current', day=date(2026, 11, 13), start=time(15), end=time(16)):
    return {1: {11: [dict(book_status=status, date=day, start_time=start, end_time=end)]}}


def test_overdue_session_blocks_current_and_next_half_hour_only():
    now = datetime(2026, 11, 15, 13, 10)
    for hour, minute, expected in [(13, 0, 0), (13, 30, 0), (14, 0, 1), (17, 0, 1)]:
        start = datetime(2026, 11, 15, hour, minute)
        assert capacity(holds(), 1, start.date(), start.time(),
                        (start + timedelta(minutes=30)).time(), now=now) == expected
    assert capacity(holds(), 1, '2026-11-16', time(13), time(14), now=now) == 1


def test_current_session_keeps_full_scheduled_interval():
    now = datetime(2026, 11, 15, 13, 10)
    bookings = holds(day=now.date(), start=time(13), end=time(17))
    assert capacity(bookings, 1, now.date(), time(16), time(17), now=now) == 0
    assert capacity(bookings, 1, now.date(), time(17), time(18), now=now) == 1


def test_overtime_crosses_midnight_and_uses_india_time():
    now = datetime(2026, 11, 15, 18, 20, tzinfo=timezone.utc)  # 23:50 IST
    assert capacity(holds(), 1, '2026-11-16', time(0), time(0, 30), now=now) == 0
    assert capacity(holds(), 1, '2026-11-16', time(0, 30), time(1), now=now) == 1


def test_upcoming_overnight_and_completed_sessions():
    now = datetime(2026, 11, 15, 13, 10)
    bookings = holds('upcoming', now.date(), time(23), time(1))
    assert capacity(bookings, 1, '2026-11-16', time(0), time(0, 30), now=now) == 0
    assert capacity(bookings, 1, '2026-11-16', time(1), time(1, 30), now=now) == 1
    assert capacity(holds('completed'), 1, now.date(), time(13), time(14), now=now) == 1
