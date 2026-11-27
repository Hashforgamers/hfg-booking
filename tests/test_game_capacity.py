"""Sellable capacity follows the consoles really mapped to a game."""
import ast
import threading
from datetime import date, time as clock_time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def compile_functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope


def listing_scope(raw, total, booked=None, qr=None, repaired=None):
    query = Mock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(total_slot=4, single_slot_price=100)
    calls = repaired if repaired is not None else []

    def repair(vendor, slot, day, raw_available, floor):
        calls.append((slot, raw_available, floor))
        return max(raw_available, floor)
    return dict(time=SimpleNamespace(time=lambda: 1), _slots_single_cache_lock=threading.Lock(),
        _slots_single_cache={}, _force_slot_refresh=lambda: True,
        AvailableGame=SimpleNamespace(query=query), SLOTS_SINGLE_CACHE_TTL_SEC=0,
        jsonify=lambda data: SimpleNamespace(json=data, headers={}),
        _load_vendor_slot_rows=lambda *args: [(1, True, raw, clock_time(9), clock_time(10))],
        load_console_holds=lambda *args: {}, free_console_capacity=lambda *args: 99,
        _load_booking_counts=lambda *args: booked or {}, _expected_blocks_for_date=lambda *args: None,
        sync_game_capacity=lambda *args: total, _load_qr_held_units=lambda *args: qr or {},
        _repair_leaked_capacity=repair, _slot_price_lookup=lambda *args: (lambda game, base, *rest: base))


def test_eleven_pcs_are_sold_even_when_rows_were_seeded_for_four():
    calls = []
    scope = compile_functions('controllers/slot_controller.py', {'get_slots_on_game_id', '_prefer_slot_candidate'},
                              listing_scope(raw=4, total=11, repaired=calls))
    response, status = scope['get_slots_on_game_id'](1, 2, '20261122')
    assert status == 200
    assert response.json['slots'][0]['available_slot'] == 11
    assert calls == [(1, 4, 11)]


def test_live_bookings_and_qr_holds_still_reduce_capacity():
    scope = compile_functions('controllers/slot_controller.py', {'get_slots_on_game_id', '_prefer_slot_candidate'},
                              listing_scope(raw=4, total=11, booked={(1, '2026-11-22'): 3}, qr={(1, '2026-11-22'): 2}))
    response, _ = scope['get_slots_on_game_id'](1, 2, '20261122')
    # floor = 11 - 3 booked - 2 QR = 6; computed cap = 11 - 3 = 8
    assert response.json['slots'][0]['available_slot'] == 6


def repair_scope(rowcount=1):
    from datetime import datetime
    from pytz import timezone
    session = Mock()
    session.execute.return_value = SimpleNamespace(rowcount=rowcount)
    return session, compile_functions('controllers/slot_controller.py', {'_repair_leaked_capacity'}, dict(
        db=SimpleNamespace(session=session), text=lambda sql: sql, datetime=datetime, timezone=timezone,
        current_app=SimpleNamespace(logger=Mock())))


def test_repair_never_lowers_a_row():
    session, scope = repair_scope()
    assert scope['_repair_leaked_capacity'](1, 7, '2099-01-01', 5, 3) == 5
    session.execute.assert_not_called()


def test_repair_skips_past_days():
    session, scope = repair_scope()
    assert scope['_repair_leaked_capacity'](1, 7, '2000-01-01', 2, 9) == 2
    session.execute.assert_not_called()


def test_repair_raises_only_an_unchanged_row():
    session, scope = repair_scope(rowcount=1)
    assert scope['_repair_leaked_capacity'](1, 7, '2099-01-01', 4, 11) == 11
    sql, params = session.execute.call_args[0]
    assert 'available_slot=:raw' in sql and params['raw'] == 4 and params['floor'] == 11
    session, scope = repair_scope(rowcount=0)  # a booking changed it meanwhile
    assert scope['_repair_leaked_capacity'](1, 7, '2099-01-01', 4, 11) == 4


def test_released_bookings_do_not_hold_capacity():
    scope = compile_functions('controllers/slot_controller.py', set(), {})
    src = (ROOT / 'controllers/slot_controller.py').read_text()
    tree = ast.parse(src)
    value = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], 'id', '') == 'RELEASED_BOOKING_STATUSES')
    statuses = ast.literal_eval(value)
    for status in ('cancelled', 'canceled', 'verification_failed', 'discarded', 'no_show', 'rejected'):
        assert status in statuses
    for status in ('confirmed', 'checked_in', 'completed', 'pending_verified', 'pending_acceptance'):
        assert status not in statuses
