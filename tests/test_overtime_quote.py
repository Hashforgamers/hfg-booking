import sys
from datetime import date, datetime, time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import overtime_quote as oq


def row(bid, start, end, day=date(2026, 11, 21)):
    return {"book_id": bid, "date": day, "start_time": start, "end_time": end}


def test_back_to_back_bookings_start_overtime_after_the_last_one():
    rows = [row(1, time(20, 0), time(20, 30)), row(2, time(20, 30), time(21, 0)), row(3, time(22, 0), time(22, 30))]
    assert oq.chain_end(rows, 1) == datetime(2026, 11, 21, 21, 0)
    assert oq.chain_end(rows, 3) == datetime(2026, 11, 21, 22, 30)


def test_slot_crossing_midnight_ends_next_day():
    assert oq.chain_end([row(9, time(23, 30), time(0, 0))], 9) == datetime(2026, 11, 22, 0, 0)


def test_rate_uses_booked_slot_length():
    assert oq.rate_per_hour(73, 1800, basis="slot") == 146
    assert oq.rate_per_hour(73, 1800, basis="hour") == 73
    assert oq.price_overtime(10 * 60, 146) == 25  # ceil(24.33)
    assert oq.price_overtime(0, 146) == 0


def fake_session(own, chain, recorded=0):
    s = MagicMock()
    results = [own, chain]
    def execute(statement, params=None):
        r = MagicMock()
        if results:
            r.mappings.return_value.all.return_value = results.pop(0)
        else:
            r.scalar.return_value = recorded
        return r
    s.execute.side_effect = execute
    return s


@pytest.fixture
def models(monkeypatch):
    game = SimpleNamespace(single_slot_price=73)
    slot = SimpleNamespace(start_time=time(20, 0), end_time=time(20, 30))
    for name, cls_name, obj in (("models.availableGame", "AvailableGame", game), ("models.slot", "Slot", slot)):
        m = ModuleType(name); model = MagicMock(); model.query.filter_by.return_value.first.return_value = obj
        setattr(m, cls_name, model); monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.setattr(oq, "RATE_BASIS", "slot")


def test_quote_subtracts_recorded_overtime_and_flags_forgotten_sessions(models):
    own = [dict(row(5, time(20, 0), time(20, 30)), user_id=1, console_id=3, book_status="current")]
    booking = SimpleNamespace(id=5, game_id=2, slot_id=7)
    q = oq.quote(fake_session(own, [], recorded=10), 41, booking, now=datetime(2026, 11, 21, 21, 0))
    assert q["overtime_seconds"] == 1800 and q["gross_amount"] == 73 and q["amount"] == 63
    assert not q["needs_end_time"]

    q = oq.quote(fake_session(own, []), 41, booking, now=datetime(2026, 11, 29, 20, 30))  # 196 hours later
    assert q["needs_end_time"]
    q = oq.quote(fake_session(own, []), 41, booking, now=datetime(2026, 11, 29, 20, 30),
                 played_until=datetime(2026, 11, 21, 21, 30))
    assert q["overtime_seconds"] == 3600 and q["amount"] == 146 and not q["needs_end_time"]


def test_played_until_cannot_be_in_the_future(models):
    own = [dict(row(5, time(20, 0), time(20, 30)), user_id=1, console_id=3, book_status="current")]
    with pytest.raises(oq.OvertimeError):
        oq.quote(fake_session(own, []), 41, SimpleNamespace(id=5, game_id=2, slot_id=7),
                 now=datetime(2026, 11, 21, 21, 0), played_until=datetime(2026, 11, 21, 22, 0))


def test_played_until_parsing():
    assert oq.parse_played_until("2026-11-21T16:00:00Z") == datetime(2026, 11, 21, 21, 30)
    assert oq.parse_played_until("2026-11-21T21:30") == datetime(2026, 11, 21, 21, 30)
    assert oq.parse_played_until("") is None
