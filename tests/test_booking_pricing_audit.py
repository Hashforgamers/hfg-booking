"""Booking pricing audit (fix/booking-pricing-audit): every path charges the same price."""
import ast
import threading
from datetime import date, datetime, time as clock_time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def compile_functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {n.name for n in nodes} == set(names), names
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope


# ---- 1. slot listings show the price checkout charges ---------------------------------

def offer(start_day, start, end_day, end, price, game=2):
    return dict(available_game_id=game, start_date=start_day, start_time=start, end_date=end_day,
                end_time=end, offered_price=Decimal(price), is_active=True)


def lookup(rows):
    from sqlalchemy import text, bindparam
    from datetime import timedelta
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = rows
    scope = compile_functions('controllers/slot_controller.py', {'_slot_price_lookup'},
                              dict(db=SimpleNamespace(session=session), text=text, bindparam=bindparam,
                                   timedelta=timedelta, current_app=SimpleNamespace(logger=Mock())))
    return scope['_slot_price_lookup'](1, [2], ['2026-11-27'])


def test_listing_price_applies_the_offer_covering_that_slot():
    # Happy hour 14:00-17:00 at Rs 40 on a Rs 60 console.
    price = lookup([offer(date(2026, 11, 27), clock_time(14), date(2026, 11, 27), clock_time(17), '40.00')])
    assert price(2, 60, '2026-11-27', clock_time(15), clock_time(16)) == 40
    assert price(2, 60, '2026-11-27', clock_time(19), clock_time(20)) == 60   # outside the offer
    assert price(2, 60, '2026-11-27', clock_time(16, 30), clock_time(17, 30)) == 60  # partly covered
    assert price(3, 80, '2026-11-27', clock_time(15), clock_time(16)) == 80   # other console


def test_listing_price_falls_back_to_base_when_offers_cannot_load():
    from sqlalchemy import text, bindparam
    from datetime import timedelta
    session = Mock()
    session.execute.side_effect = RuntimeError('db down')
    scope = compile_functions('controllers/slot_controller.py', {'_slot_price_lookup'},
                              dict(db=SimpleNamespace(session=session), text=text, bindparam=bindparam,
                                   timedelta=timedelta, current_app=SimpleNamespace(logger=Mock())))
    price = scope['_slot_price_lookup'](1, [2], ['2026-11-27'])
    assert price(2, 60, '2026-11-27', clock_time(15), clock_time(16)) == 60


def test_single_listing_returns_offer_price_and_base_price():
    query = Mock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(total_slot=3, single_slot_price=60)
    scope = dict(time=SimpleNamespace(time=lambda: 1), _slots_single_cache_lock=threading.Lock(),
        _slots_single_cache={}, _force_slot_refresh=lambda: True,
        AvailableGame=SimpleNamespace(query=query), SLOTS_SINGLE_CACHE_TTL_SEC=0,
        jsonify=lambda data: SimpleNamespace(json=data, headers={}),
        _load_vendor_slot_rows=lambda *args: [(1, True, 3, clock_time(15), clock_time(16))],
        load_console_holds=lambda *args: {}, free_console_capacity=lambda *args: 3,
        _load_booking_counts=lambda *args: {}, _expected_blocks_for_date=lambda *args: None,
        sync_game_capacity=lambda *args: 3, _load_qr_held_units=lambda *args: {},
        _repair_leaked_capacity=lambda vendor, slot, day, raw, floor: raw,
        _slot_price_lookup=lambda *args: (lambda game, base, day, start, end: 40))
    compile_functions('controllers/slot_controller.py', {'get_slots_on_game_id', '_prefer_slot_candidate'}, scope)
    response, status = scope['get_slots_on_game_id'](1, 2, '20261127')
    assert status == 200
    assert response.json['slots'][0]['single_slot_price'] == 40
    assert response.json['slots'][0]['base_slot_price'] == 60


# ---- 2. app checkout voucher matches the app's own total ------------------------------

def money_helpers():
    from decimal import ROUND_HALF_UP
    return compile_functions('controllers/booking_controller.py', {'voucher_discount_amount', 'gateway_amount_matches'},
                             dict(Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP))


def test_voucher_discounts_every_booking_to_the_paisa():
    h = money_helpers()
    # Two Rs 100 slots + 10% voucher: the app charges Rs 180. The old code
    # discounted only the first booking (Rs 190) and the payment was rejected.
    lines = [100.0, 100.0]
    total = sum(line - h['voucher_discount_amount'](line, 10) for line in lines)
    assert total == 180.0
    # 15% of Rs 95: Rs 14.25 off (the old int() gave Rs 14).
    assert h['voucher_discount_amount'](95, 15) == 14.25
    assert h['voucher_discount_amount'](50, 150) == 50.0   # never more than the line


def test_gateway_accepts_the_apps_one_paisa_truncation_only():
    h = money_helpers()
    assert h['gateway_amount_matches'](6633, 6633)
    assert h['gateway_amount_matches'](6632, 6633)        # app: int(66.33 * 100) == 6632
    assert not h['gateway_amount_matches'](6631, 6633)
    assert not h['gateway_amount_matches'](6634, 6633)    # never accept an overpayment
    assert not h['gateway_amount_matches']('x', 6633)


# ---- 3. food on a multi-slot booking is recorded once ---------------------------------

def test_food_is_attached_to_one_booking_only():
    source = (ROOT / 'controllers/booking_controller.py').read_text()
    assert 'required_qty_by_menu[menu_id] += int(meal_detail.get("quantity") or 0)\n' in source
    assert '* len(bookings)' not in source.split('def new_booking', 1)[1].split('def cancel_bookings_with_refund', 1)[0]
    assert 'for booking in bookings[:1]:' in source
    assert 'for extra in (extra_services_list if not extras_saved else []):' in source


# ---- 4. pay-at-cafe squads pay the controller fare once -------------------------------

def pay_at_cafe_scope(controller_fare=60.0):
    scope = dict(
        get_effective_price_for_schedule=lambda *a, **k: 100.0,
        get_effective_price=lambda *a, **k: 100.0,
        current_app=SimpleNamespace(logger=Mock()),
        _resolve_console_group=lambda *a, **k: 'ps5',
        _resolve_squad_pricing_mode=lambda *a, **k: 'controller_pricing',
        _resolve_squad_discount_percent=lambda *a, **k: 0.0,
        _load_squad_pricing_policy=lambda *a, **k: {},
        _requires_multi_console_units=lambda *a, **k: False,
        is_controller_pricing_supported=lambda *a, **k: True,
        calculate_extra_controller_fare=lambda vendor_id, available_game_id, quantity: controller_fare,
    )
    return compile_functions('controllers/booking_controller.py', {'_compute_pay_at_cafe_pricing'}, scope)


def test_pay_at_cafe_squad_controller_fare_is_charged_on_one_slot():
    scope = pay_at_cafe_scope()
    game = SimpleNamespace(id=2, game_name='PS5')
    squad = {'enabled': True, 'player_count': 3, 'pricing_mode': 'controller_pricing', 'batch_id': 'b1'}
    slots = [scope['_compute_pay_at_cafe_pricing'](1, game, squad, booking_date=date(2026, 11, 27),
                                                   include_controller=index == 0) for index in range(2)]
    # 2 slots x Rs 100 + 2 extra controllers Rs 60 once = Rs 260 (was Rs 320).
    assert [s['final_amount'] for s in slots] == [160.0, 100.0]
    assert slots[1]['controller_qty'] == 0


def test_accept_and_pending_list_pass_include_controller():
    source = (ROOT / 'controllers/booking_controller.py').read_text()
    assert source.count('include_controller=') >= 3


# ---- 5. PC squad overtime: shown amount == charged amount, earlier lines subtracted ----

def test_pc_squad_slot_rate_overtime_is_priced_for_the_whole_squad(monkeypatch):
    import sys
    from types import ModuleType
    from services import overtime_quote as oq
    from tests.test_overtime_quote import fake_session, row
    game = SimpleNamespace(single_slot_price=60)
    slot = SimpleNamespace(start_time=clock_time(20, 0), end_time=clock_time(21, 0))
    for name, cls_name, obj in (("models.availableGame", "AvailableGame", game), ("models.slot", "Slot", slot)):
        m = ModuleType(name); model = Mock(); model.query.filter_by.return_value.first.return_value = obj
        setattr(m, cls_name, model); monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.setattr(oq, "RATE_BASIS", "slot")
    monkeypatch.setattr(oq, "load_rate_cards", lambda *a: ("slot", []))
    own = [dict(row(5, clock_time(20, 0), clock_time(21, 0)), user_id=1, console_id=3, book_status="current")]
    squad = SimpleNamespace(id=5, game_id=2, slot_id=7, squad_details={"player_count": 3, "enabled": True})
    # 30 minutes over, nothing billed yet: 3 players x Rs 30 = Rs 90, shown as Rs 90.
    q = oq.quote(fake_session(own, []), 41, squad, now=datetime(2026, 11, 21, 21, 30), squad_multiplier=3)
    assert q["amount"] == 90 and q["gross_amount"] == 90 and q["amount_covers_squad"] and q["rate_per_hour"] == 180
    # 60 minutes over with that Rs 90 already billed: Rs 90 more (the old code returned Rs 0).
    q = oq.quote(fake_session(own, [], recorded=90), 41, squad, now=datetime(2026, 11, 21, 22, 0), squad_multiplier=3)
    assert q["gross_amount"] == 180 and q["amount"] == 90


# ---- 6. flex windows pay each slot's own price ----------------------------------------

def test_blended_price_uses_each_covered_slots_rate():
    from services import flex_timing as ft
    d = date(2026, 11, 27)
    at = lambda h, m=0: datetime.combine(d, clock_time(h, m))
    slots = [(at(18), at(19), 60), (at(19), at(20), 40), (at(20), at(21), 60)]
    # 18:30-20:30 = 30 + 40 + 30 = Rs 100 (was 2 x Rs 60 = Rs 120).
    blended = ft.blended_slot_price(at(18, 30), at(20, 30), slots, 60)
    assert ft.fallback_price(120, blended, 60, 15) == Decimal("100.00")
    # 19:30-21:30 with the offer on the base slot: 20 + 60 + 30 = Rs 110 (was 2 x Rs 40 = Rs 80).
    slots = [(at(19), at(20), 40), (at(20), at(21), 60), (at(21), at(22), 60)]
    blended = ft.blended_slot_price(at(19, 30), at(21, 30), slots, 60)
    assert ft.fallback_price(120, blended, 60, 15) == Decimal("110.00")
    assert ft.blended_slot_price(at(9), at(10), slots, 60) is None


# ---- 7. overnight slots have a real length --------------------------------------------

def test_overnight_slot_minutes():
    from datetime import timedelta
    scope = compile_functions('controllers/booking_controller.py', {'calculate_slot_minutes'},
                              dict(datetime=datetime, timedelta=timedelta, Slot=object))
    assert scope['calculate_slot_minutes'](SimpleNamespace(start_time=clock_time(23, 30), end_time=clock_time(0, 30))) == 60
    assert scope['calculate_slot_minutes'](SimpleNamespace(start_time=clock_time(10), end_time=clock_time(11))) == 60
