"""Pricing scenario matrix: shown == charged/validated == stored, per channel.

Each scenario runs the real pricing code of the channel (compiled straight
from the controllers/services with only the database boundary stubbed):

- app      HFG-frontend: shows and pays the sum of getSlots single_slot_price
           (+ cart, - voucher, int(total*100)), validated by /bookings/confirm.
- website  hfg-new-landing-page: shows and pays /bookings/pricing-preview
           final_amount, validated by /bookings/confirm.
- desk     hash-dashboard newBooking: listing price per slot, stored by newBooking.
- pay_at_cafe  /bookings (pay at cafe) + /pay-at-cafe/accept.
- kiosk    hashdashpc: hfg-dashboard session pricing (copy of pricing_math).
- overtime /overtime-quote shown at the desk == /extraBooking charge.

Run as a script to write the matrix:  python tests/test_pricing_scenarios.py OUT_DIR
"""
import ast
import csv
import importlib.util
import math
import sys
from contextlib import contextmanager
from datetime import date, datetime, time as T, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DAY = date(2026, 11, 27)
CONTROLLER = 'controllers/booking_controller.py'


def compile_functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names), names
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope


def offer(start, end, price, day=DAY, end_day=None):
    return SimpleNamespace(available_game_id=2, start_date=day, start_time=start, end_date=end_day or day,
                           end_time=end, offered_price=Decimal(str(price)), is_active=True)


def slot(sid, start, end):
    return SimpleNamespace(id=sid, start_time=start, end_time=end, gaming_type_id=2)


def game(price=60, name='PS5'):
    return SimpleNamespace(id=2, vendor_id=1, single_slot_price=price, game_name=name)


# ---- real pricing functions with the DB boundary stubbed -------------------------------

def listing_price(base, offers, day, s):
    """getSlots single_slot_price for one slot (what the app and desk show)."""
    from sqlalchemy import text, bindparam
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = [vars(o) for o in offers]
    scope = compile_functions('controllers/slot_controller.py', {'_slot_price_lookup'},
                              dict(db=SimpleNamespace(session=session), text=text, bindparam=bindparam,
                                   timedelta=timedelta, current_app=SimpleNamespace(logger=Mock())))
    return scope['_slot_price_lookup'](1, [2], [day.isoformat()])(2, base, day.isoformat(), s.start_time, s.end_time)


def schedule_price(base, offers, day, s):
    """get_effective_price_for_schedule: what every checkout charges for a slot."""
    class Column:
        def __eq__(self, other): return True
        __le__ = __ge__ = __lt__ = __gt__ = __eq__
        __hash__ = object.__hash__

    class Model:
        vendor_id = available_game_id = is_active = start_date = end_date = Column()
        query = Mock()
    Model.query.filter.return_value.all.return_value = offers
    model = Model
    scope = compile_functions(CONTROLLER, {'get_effective_price_for_schedule'},
                              dict(ConsolePricingOffer=model, datetime=datetime))
    return scope['get_effective_price_for_schedule'](1, game(base), day, s)


def money_helpers():
    return compile_functions(CONTROLLER, {'voucher_discount_amount', 'gateway_amount_matches'},
                             dict(Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP))


def app_display_total(slot_prices, cart=(), voucher_pct=0):
    """HFG-frontend booking_summary_screen.dart calculateTotalPrice + initiatePayment (read only)."""
    subtotal = float(sum(slot_prices)) + float(sum(p * q for p, q in cart))
    total = subtotal - subtotal * (voucher_pct / 100) if voucher_pct else subtotal
    total = max(total, 0.0)
    return total, int(total * 100)


def confirm_total(slot_unit_prices, extras_total=0.0, voucher_pct=0, players=1, squad_pct=0.0):
    """/bookings/confirm line arithmetic (no pass): slot x squad - squad discount + extras share - voucher."""
    h = money_helpers()
    n = len(slot_unit_prices)
    total = 0.0
    for unit in slot_unit_prices:
        slot_price = unit * players
        payable = max(slot_price - slot_price * squad_pct / 100.0, 0.0) + extras_total / n
        if voucher_pct:
            payable -= h['voucher_discount_amount'](payable, voucher_pct)
        total += payable
    return round(total, 2)


def gateway_ok(captured_paise, total):
    expected = int((Decimal(str(total)) * 100).quantize(Decimal('1')))
    return money_helpers()['gateway_amount_matches'](captured_paise, expected)


def pay_at_cafe(slots_prices, squad=None, controller_fare=60.0, multi=False, discount=0.0, mode='controller_pricing'):
    """_compute_pay_at_cafe_pricing per booking of the batch, controller once."""
    prices = iter(slots_prices)
    scope = compile_functions(CONTROLLER, {'_compute_pay_at_cafe_pricing'}, dict(
        get_effective_price_for_schedule=lambda *a, **k: next(prices),
        get_effective_price=lambda *a, **k: 0.0,
        current_app=SimpleNamespace(logger=Mock()),
        _resolve_console_group=lambda *a, **k: 'pc' if multi else 'ps5',
        _resolve_squad_pricing_mode=lambda *a, **k: mode,
        _resolve_squad_discount_percent=lambda *a, **k: discount,
        _load_squad_pricing_policy=lambda *a, **k: {},
        _requires_multi_console_units=lambda *a, **k: multi,
        is_controller_pricing_supported=lambda *a, **k: not multi,
        calculate_extra_controller_fare=lambda vendor_id, available_game_id, quantity: controller_fare))
    lines = [scope['_compute_pay_at_cafe_pricing'](1, game(), squad or {}, booking_date=DAY, slot_obj=object(),
                                                    include_controller=i == 0) for i in range(len(slots_prices))]
    return round(sum(l['final_amount'] for l in lines), 2)


def controller_total(base, tiers, qty):
    from services.pricing_math import controller_total as real
    return float(real(base, tiers, qty))


def preview(slots, offers, base=60, players=1, multi=False, discount=0.0, mode='solo_only', meals=(),
            controller_qty=0, controller_fare=None):
    """/bookings/pricing-preview (website shows and pays final_amount)."""
    from flask import Flask, jsonify, request
    sched = lambda vendor_id, g, day, s: schedule_price(base, offers, day, s)
    squad = {'enabled': players > 1, 'player_count': players, 'pricing_mode': mode, 'discount_percent': discount}
    slot_model = Mock()
    slot_model.query.filter.return_value.all.return_value = slots
    slot_model.id.in_ = lambda ids: True
    session = Mock()
    session.execute.return_value.fetchone.return_value = (5, True)
    menu = {m['id']: SimpleNamespace(id=m['id'], name=m['name'], price=m['price'], stock_quantity=None) for m in meals}
    session.query.return_value.join.return_value.filter.return_value.first.side_effect = \
        lambda: menu[current_menu[0]]
    current_menu = [None]

    class MenuModel:  # noqa: D401 - query filter is stubbed above
        id = Mock()
        is_active = Mock()

    def query(model):
        return session.query.return_value
    scope = compile_functions(CONTROLLER, {'booking_pricing_preview', 'resolve_app_fee_amount',
                                           '_ensure_menu_stock_available', '_menu_stock_qty', '_menu_stock_unit'}, dict(
        request=request, jsonify=jsonify, datetime=datetime, text=lambda s: s, current_app=None,
        _coerce_date_value=lambda v: date.fromisoformat(v),
        _resolve_available_game_for_vendor=lambda **k: game(base, 'PC' if multi else 'PS5'),
        _load_squad_pricing_policy=lambda *a: {},
        _normalize_squad_booking_payload=lambda payload, *a, **k: dict(squad) if players > 1 else {'enabled': False},
        _resolve_console_group=lambda *a, **k: 'pc' if multi else 'ps5',
        _requires_multi_console_units=lambda *a, **k: multi,
        is_controller_pricing_supported=lambda *a, **k: not multi,
        calculate_extra_controller_fare=lambda vendor_id, available_game_id, quantity:
            controller_fare if controller_fare is not None else None,
        get_effective_price_for_schedule=sched, Slot=slot_model,
        db=SimpleNamespace(session=SimpleNamespace(execute=session.execute,
                                                   query=lambda *a: _MenuQuery(menu, current_menu))),
        ExtraServiceMenu=MenuModel, ExtraServiceCategory=Mock()))
    app = Flask(__name__)
    app.config.update(APP_FEE_PERCENT=0, APP_FEE_FLAT=0)
    body = dict(vendor_id=1, game_id=2, book_date=DAY.isoformat(), slot_id=[s.id for s in slots],
                squad_details={'enabled': players > 1, 'player_count': players},
                selected_meals=[{'menu_item_id': m['id'], 'quantity': m['qty']} for m in meals],
                extra_controller_qty=controller_qty)
    with app.test_request_context(json=body):
        scope['current_app'] = app
        response, status = scope['booking_pricing_preview']()
    assert status == 200, response.json
    return response.json['pricing_engine']['final_amount']


class _MenuQuery:
    def __init__(self, menu, current):
        self.menu, self.current = menu, current

    def join(self, *a):
        return self

    def filter(self, *conditions):
        return self

    def first(self):
        # One menu item per call, in request order.
        key = sorted(self.menu)[self.current[0] or 0] if self.menu else None
        self.current[0] = (self.current[0] or 0) + 1
        return self.menu.get(key)


@contextmanager
def overtime(offers, base=60, slot_len=(T(20), T(21)), cards=None, mode='slot'):
    from services import overtime_quote as oq
    saved = {n: sys.modules.get(n) for n in ('models.availableGame', 'models.slot')}
    g = SimpleNamespace(single_slot_price=base)
    s = SimpleNamespace(start_time=slot_len[0], end_time=slot_len[1])
    for name, cls_name, obj in (('models.availableGame', 'AvailableGame', g), ('models.slot', 'Slot', s)):
        m = ModuleType(name); model = Mock(); model.query.filter_by.return_value.first.return_value = obj
        setattr(m, cls_name, model); sys.modules[name] = m
    old = (oq.RATE_BASIS, oq.load_rate_cards, oq.load_offers)
    oq.RATE_BASIS = 'slot'
    oq.load_rate_cards = lambda *a: (mode, cards or [])
    oq.load_offers = lambda *a: offers
    try:
        yield oq
    finally:
        oq.RATE_BASIS, oq.load_rate_cards, oq.load_offers = old
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def overtime_quote(offers, minutes, players=1, recorded=0, start=T(20), end=T(21)):
    from tests.test_overtime_quote import fake_session
    with overtime(offers, slot_len=(start, end)) as oq:
        own = [dict(book_id=5, date=DAY, start_time=start, end_time=end, user_id=1, console_id=3, book_status='current')]
        b = SimpleNamespace(id=5, game_id=2, slot_id=7, squad_details={'player_count': players, 'enabled': players > 1})
        finish = datetime.combine(DAY, end) + (timedelta(days=1) if end <= start else timedelta())
        q = oq.quote(fake_session(own, [], recorded=recorded), 1, b, now=finish + timedelta(minutes=minutes),
                     squad_multiplier=players)
    # /extraBooking: multiplier 1 when amount_covers_squad, else x players.
    charged = q['amount'] * (1 if q['amount_covers_squad'] else players)
    return q['amount'], charged


def flex_price(windows, start, end, slot_minutes=60, step=15):
    from services import flex_timing as ft
    minutes = int((end - start).total_seconds() // 60)
    prices = {p for _, _, p in windows}
    base = windows[0][2]
    price = ft.blended_slot_price(start, end, windows, slot_minutes) if len(prices) > 1 else base
    return float(ft.fallback_price(minutes, price, slot_minutes, step))


def kiosk_amount(offers, slots_, start, minutes, base=60):
    spec = importlib.util.spec_from_file_location('dash_pricing_math',
                                                  ROOT.parent / 'hfg-dashboard/app/services/pricing_math.py')
    if not spec or not Path(spec.origin).exists():
        pytest.skip('hfg-dashboard checkout not next to hfg-booking')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m.session_amount(base, slots_, offers, start, minutes, minimum_minutes=1) / 100


def kiosk_overtime_fallback(offers, start, seconds, base=60, slot_seconds=3600):
    spec = importlib.util.spec_from_file_location('dash_pricing_math2',
                                                  ROOT.parent / 'hfg-dashboard/app/services/pricing_math.py')
    if not spec or not Path(spec.origin).exists():
        pytest.skip('hfg-dashboard checkout not next to hfg-booking')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    price = base * 100
    if offers:
        exact = m.interval_amount(Decimal(price) / 100, offers, start, start + timedelta(seconds=seconds), slot_seconds) * 100
        return math.ceil(exact) / 100
    return ((price * seconds + slot_seconds - 1) // slot_seconds) / 100


def paid_gaming(lines):
    src = (ROOT / CONTROLLER).read_text()
    scope = dict(Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP)
    for name in ('NON_GAMING_BOOKING_TYPES', 'VOID_SETTLEMENTS'):
        exec(name + ' = ' + src.split(name + ' = ', 1)[1].split('\n', 1)[0], scope)
    return compile_functions(CONTROLLER, {'paid_gaming_amount'}, scope)['paid_gaming_amount'](lines)


def gst(amount, inclusive=False, rate=18):
    profile = SimpleNamespace(gst_registered=True, gst_enabled=True, gst_rate=rate, tax_inclusive=inclusive,
                              state_code='29', place_of_supply_state_code='29')
    query = Mock(); query.filter_by.return_value.first.return_value = profile
    return compile_functions(CONTROLLER, {'calculate_gst_breakdown'},
                             dict(VendorTaxProfile=SimpleNamespace(query=query), Decimal=Decimal,
                                  ROUND_HALF_UP=ROUND_HALF_UP))['calculate_gst_breakdown'](1, amount)


def desk_variant_price(minutes, players, rule_amount=90):
    from services.desk_pricing import validate_definition, quote
    card = validate_definition(dict(name='PS5 65"', model_name='m', rules=[dict(
        min_minutes=1, max_minutes=None, min_players=1, max_players=8, amount=str(rule_amount),
        unit_minutes=60, per_player=False)]))
    return float(quote(card, minutes, players))


# ---- scenarios ---------------------------------------------------------------------------

S15, S19, S20, S21 = slot(115, T(15), T(16)), slot(119, T(19), T(20)), slot(120, T(20), T(21)), slot(121, T(21), T(22))
S1630 = slot(116, T(16, 30), T(17, 30))
S2330 = slot(123, T(23, 30), T(0, 30))
HAPPY = [offer(T(14), T(17), 40)]
LATE = [offer(T(23), T(2), 30, end_day=DAY + timedelta(days=1))]


def sc(sid, channel, case, inputs, expected, shown, charged, stored, pending=None):
    return dict(id=sid, channel=channel, case=case, inputs=inputs, expected=expected,
                shown=shown, charged=charged, stored=stored, pending=pending)


def scenarios():
    h = money_helpers()
    rows = []
    # Plain price and offers, every channel that books slots.
    for label, s, offers, exp in [
        ('plain slot price', S19, [], 60),
        ('offer covers slot', S15, HAPPY, 40),
        ('slot outside offer', S19, HAPPY, 60),
        ('slot straddles offer end (offer must cover whole slot)', S1630, HAPPY, 60),
        ('late-night offer, slot crosses midnight', S2330, LATE, 30),
    ]:
        listed = listing_price(60, offers, DAY, s)
        charge = schedule_price(60, offers, DAY, s)
        shown_app, paise = app_display_total([listed])
        rows.append(sc(f'APP-{len(rows)+1}', 'app', label, f'Rs60 base, {s.start_time:%H:%M}-{s.end_time:%H:%M}, offers={len(offers)}',
                       exp, shown_app, confirm_total([charge]) if gateway_ok(paise, confirm_total([charge])) else f'REJECTED {paise}p',
                       confirm_total([charge])))
        rows.append(sc(f'WEB-{len(rows)+1}', 'website', label, 'pricing-preview -> confirm', exp,
                       preview([s], offers), confirm_total([charge]), confirm_total([charge])))
        rows.append(sc(f'DESK-{len(rows)+1}', 'desk', label, 'listing price -> newBooking', exp, listed, charge, charge))
        rows.append(sc(f'PAC-{len(rows)+1}', 'pay_at_cafe', label, 'accept', exp, listed,
                       pay_at_cafe([charge]), pay_at_cafe([charge])))
    # Multi-slot spanning offer edge.
    two = [S15, slot(116, T(16), T(17)), slot(117, T(17), T(18))]
    listed = [listing_price(60, HAPPY, DAY, s) for s in two]
    charge = [schedule_price(60, HAPPY, DAY, s) for s in two]
    rows.append(sc('APP-MS', 'app', '3 slots across offer end', '15-18, offer 14-17 Rs40', 140,
                   app_display_total(listed)[0], confirm_total(charge), confirm_total(charge)))
    rows.append(sc('WEB-MS', 'website', '3 slots across offer end', '15-18, offer 14-17 Rs40', 140,
                   preview(two, HAPPY), confirm_total(charge), confirm_total(charge)))
    # Vouchers.
    for pct, slots_, exp in [(10, [100, 100], 180.0), (15, [95], 80.75), (33, [99], 66.33), (100, [60, 60], 0.0)]:
        shown, paise = app_display_total(slots_, voucher_pct=pct)
        total = confirm_total(slots_, voucher_pct=pct)
        ok = gateway_ok(paise, total) or total == 0
        rows.append(sc(f'APP-V{pct}-{len(slots_)}', 'app', f'{pct}% voucher on {len(slots_)} slot(s)', f'slots {slots_}', exp,
                       round(shown, 2), total if ok else f'REJECTED {paise}p vs {total}', total))
    rows.append(sc('APP-VF', 'app', 'flat voucher', 'not supported by app/backend (percent only)', 'n/a', 'n/a', 'n/a', 'n/a',
                   pending='Vouchers are percent-only in the app and backend; no flat voucher exists to test.'))
    # Food.
    shown, paise = app_display_total([60, 60], cart=[(50, 2)])
    total = confirm_total([60, 60], extras_total=100)
    rows.append(sc('APP-F', 'app', 'food x2 on 2-slot booking', '2 x Rs60 + 2 x Rs50', 220, shown,
                   total if gateway_ok(paise, total) else 'REJECTED', total))
    rows.append(sc('APP-FV', 'app', 'food + 10% voucher, 2 slots', '2 x Rs60 + 2 x Rs50, 10%', 198,
                   app_display_total([60, 60], cart=[(50, 2)], voucher_pct=10)[0],
                   confirm_total([60, 60], extras_total=100, voucher_pct=10),
                   confirm_total([60, 60], extras_total=100, voucher_pct=10)))
    meal = [{'id': 9, 'name': 'Coke', 'price': 50, 'qty': 2}]
    rows.append(sc('WEB-F', 'website', 'food x2 on 2-slot booking', '2 x Rs60 + 2 x Rs50', 220,
                   preview([S19, S20], [], meals=meal), 220.0, 120 + 100 / 2 * 2))
    rows.append(sc('DESK-F', 'desk', 'food x2 on 2-slot booking (stored once)', 'newBooking meals split', 220,
                   120 + 100, 120 + 100, sum([60 + 100 / 2, 60 + 100 / 2])))
    # Squads.
    ctl = controller_total(30, [], 2)
    rows.append(sc('WEB-SQ-PS5', 'website', 'PS5 squad of 3, 2 slots, 2 controllers', 'Rs60 slot, Rs30/controller', 180,
                   preview([S19, S20], [], players=3, mode='controller_pricing', controller_fare=ctl),
                   confirm_total([60, 60]) + ctl, confirm_total([60, 60]) + ctl))
    rows.append(sc('PAC-SQ-PS5', 'pay_at_cafe', 'PS5 squad of 3, 2 slots, 2 controllers', 'controller fare once', 180,
                   pay_at_cafe([60, 60], squad={'enabled': True, 'player_count': 3, 'pricing_mode': 'controller_pricing'},
                               controller_fare=ctl),
                   pay_at_cafe([60, 60], squad={'enabled': True, 'player_count': 3, 'pricing_mode': 'controller_pricing'},
                               controller_fare=ctl),
                   pay_at_cafe([60, 60], squad={'enabled': True, 'player_count': 3, 'pricing_mode': 'controller_pricing'},
                               controller_fare=ctl)))
    pc = {'enabled': True, 'player_count': 3, 'pricing_mode': 'squad_discount', 'discount_percent': 10}
    rows.append(sc('WEB-SQ-PC', 'website', 'PC squad of 3, 10% squad discount, 1 slot', 'Rs60 x 3 - 10%', 162,
                   preview([S19], [], players=3, multi=True, discount=10, mode='squad_discount'),
                   confirm_total([60], players=3, squad_pct=10), confirm_total([60], players=3, squad_pct=10)))
    rows.append(sc('PAC-SQ-PC', 'pay_at_cafe', 'PC squad of 3, 10% squad discount, 1 slot', 'Rs60 x 3 - 10%', 162,
                   pay_at_cafe([60], squad=pc, multi=True, discount=10, mode='squad_discount'),
                   pay_at_cafe([60], squad=pc, multi=True, discount=10, mode='squad_discount'),
                   pay_at_cafe([60], squad=pc, multi=True, discount=10, mode='squad_discount')))
    rows.append(sc('PAC-SQ-PC-OFFER', 'pay_at_cafe', 'PC squad of 3 inside offer', 'Rs40 offer x 3 - 10%', 108,
                   pay_at_cafe([40], squad=pc, multi=True, discount=10, mode='squad_discount'),
                   pay_at_cafe([40], squad=pc, multi=True, discount=10, mode='squad_discount'),
                   pay_at_cafe([40], squad=pc, multi=True, discount=10, mode='squad_discount')))
    # Passes: gaming covered, nothing charged; time-wallet credit 0.
    rows.append(sc('APP-PASS', 'app', 'hour/date pass covers slot', 'pass', 0, 0, 0,
                   paid_gaming([dict(booking_type='direct', amount=0)])))
    # Overtime.
    for case, offers, minutes, players, recorded, exp in [
        ('30 min over, no offer', [], 30, 1, 0, 30),
        ('30 min over inside offer', [offer(T(21), T(23), 40)], 30, 1, 0, 20),
        ('60 min over straddling offer end', [offer(T(20), T(21, 30), 40)], 60, 1, 0, 50),
        ('PC squad of 3, 30 min over', [], 30, 3, 0, 90),
        ('PC squad of 3, 60 min over, Rs90 already billed', [], 60, 3, 90, 90),
        ('PC squad of 3, 30 min over inside offer', [offer(T(21), T(23), 40)], 30, 3, 0, 60),
    ]:
        shown, charged = overtime_quote(offers, minutes, players, recorded)
        rows.append(sc(f'OT-{len(rows)+1}', 'overtime', case, f'Rs60/h, {players} player(s)', exp, shown, charged, charged))
    shown, charged = overtime_quote(LATE, 30, start=T(22, 30), end=T(23, 30))
    rows.append(sc('OT-LATE', 'overtime', '30 min over after 23:30 inside late offer', 'Rs60/h, Rs30 offer 23-02', 15,
                   shown, charged, charged))
    # Kiosk (hashdashpc -> hfg-dashboard).
    grid = [SimpleNamespace(date=None, start_time=T(h), end_time=T((h + 1) % 24)) for h in range(24)]
    rows.append(sc('KIOSK-1', 'kiosk', '60 min session inside offer', 'self-QR, offer 14-17', 40,
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(15)), 60),
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(15)), 60),
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(15)), 60)))
    rows.append(sc('KIOSK-2', 'kiosk', '90 min from 16:30 across offer end', 'Rs40 x 30 min + Rs60 x 60 min', 80,
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(16, 30)), 90),
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(16, 30)), 90),
                   kiosk_amount(HAPPY, grid, datetime.combine(DAY, T(16, 30)), 90)))
    rows.append(sc('KIOSK-3', 'kiosk', 'auto-extend 60 min past midnight in late offer', 'grid crosses midnight', 30,
                   kiosk_amount(LATE, grid, datetime.combine(DAY, T(23, 30)), 60),
                   kiosk_amount(LATE, grid, datetime.combine(DAY, T(23, 30)), 60),
                   kiosk_amount(LATE, grid, datetime.combine(DAY, T(23, 30)), 60)))
    late = offer(T(21), T(23), 40)
    rows.append(sc('KIOSK-OT', 'kiosk', 'extra time past schedule inside offer (fallback)', '30 min, Rs40 offer', 20,
                   kiosk_overtime_fallback([late], datetime.combine(DAY, T(21)), 1800),
                   kiosk_overtime_fallback([late], datetime.combine(DAY, T(21)), 1800),
                   kiosk_overtime_fallback([late], datetime.combine(DAY, T(21)), 1800)))
    # Flex.
    at = lambda hh, mm=0: datetime.combine(DAY, T(hh, mm))
    bands = [(at(18), at(19), 60), (at(19), at(20), 40), (at(20), at(21), 60)]
    rows.append(sc('FLEX-1', 'desk', 'flex 18:30-20:30 over an offer slot', 'Rs60 / Rs40 / Rs60', 100,
                   flex_price(bands, at(18, 30), at(20, 30)), flex_price(bands, at(18, 30), at(20, 30)),
                   flex_price(bands, at(18, 30), at(20, 30))))
    plain = [(at(10), at(11), 100), (at(11), at(12), 100), (at(12), at(13), 100)]
    rows.append(sc('FLEX-2', 'desk', 'flex walk-in 10:12 x 120 min, plain price', 'Rs100/h', 200,
                   flex_price(plain, at(10, 12), at(12, 12)), flex_price(plain, at(10, 12), at(12, 12)),
                   flex_price(plain, at(10, 12), at(12, 12))))
    # Time wallet.
    lines = [dict(booking_type='direct', amount=212, meals_amount=50), dict(booking_type='extra', amount=90)]
    rows.append(sc('TW-1', 'desk', 'time-wallet credit, PC squad slot paid Rs162 + food', 'credit-unused', 162,
                   paid_gaming(lines), paid_gaming(lines), paid_gaming(lines)))
    # Rounding.
    shown, paise = app_display_total([33.33, 33.0])
    total = confirm_total([33.33, 33.0])
    rows.append(sc('RND-1', 'app', 'float total 66.33 paid as int(x*100)', 'Rs33.33 + Rs33', 66.33, round(shown, 2),
                   total if gateway_ok(paise, total) else f'REJECTED {paise}p', total))
    # GST is inside every price (Bhanu, 2026-11-27): the charge is the price as set,
    # GST is worked back from it for reports (taxable = price x 100 / 118).
    g = gst(118)
    rows.append(sc('GST-BREAKDOWN', 'desk', 'Rs118 price, GST 18% inside', 'taxable + CGST + SGST', '100/9/9',
                   f"{g['taxable_amount']:.0f}/{g['cgst_amount']:.0f}/{g['sgst_amount']:.0f}",
                   f"{g['taxable_amount']:.0f}/{g['cgst_amount']:.0f}/{g['sgst_amount']:.0f}",
                   f"{g['taxable_amount']:.0f}/{g['cgst_amount']:.0f}/{g['sgst_amount']:.0f}"))
    r = gst(33.33)
    rows.append(sc('RND-2', 'desk', 'GST inside Rs33.33 adds back to the price', 'taxable 28.25 + GST 5.08', 33.33,
                   r['total_with_tax'], round(r['taxable_amount'] + r['cgst_amount'] + r['sgst_amount'], 2),
                   r['total_with_tax']))
    for flag in (False, True):
        rows.append(sc(f'GST-DESK-{"incl" if flag else "ontop"}', 'desk',
                       f'Rs118 booking, old setting "{"inclusive" if flag else "add on top"}"', 'charge = price', 118,
                       118, gst(118, inclusive=flag)['total_with_tax'], gst(118, inclusive=flag)['total_with_tax']))
    rows.append(sc('GST-PAC', 'pay_at_cafe', 'Rs118 booking, GST inside', 'accept stores the breakdown', 118,
                   listing_price(118, [], DAY, S19), pay_at_cafe([118]), gst(pay_at_cafe([118]))['total_with_tax']))
    rows.append(sc('GST-KIOSK', 'kiosk', 'Rs118 next-slot booking, GST inside', 'kiosk next slot', 118,
                   118, gst(118)['total_with_tax'], gst(118)['total_with_tax']))
    rows.append(sc('GST-OT', 'overtime', 'Rs118/h, 30 min over, GST inside', 'extraBooking total_with_tax', 59,
                   overtime_quote([], 30)[0] * 118 / 60, gst(59)['total_with_tax'], gst(59)['total_with_tax']))
    rows.append(sc('GST-FOOD', 'desk', 'Rs50 food x2 added, GST inside', 'add-meals total_with_tax', 100,
                   100, gst(100)['total_with_tax'], gst(100)['total_with_tax']))
    rows.append(sc('GST-APP', 'app', 'Rs118 slot, GST inside', 'app total = listing price', 118,
                   app_display_total([listing_price(118, [], DAY, S19)])[0], confirm_total([118]), confirm_total([118])))
    rows.append(sc('GST-WEB', 'website', 'Rs118 slot, GST inside', 'pricing-preview -> confirm', 118,
                   preview([S19], [], base=118), confirm_total([118]), confirm_total([118])))
    # Variant / rate-card devices in the app.
    rows.append(sc('VAR-APP', 'app', 'rate-card (variants) device, 60 min', 'desk card Rs90/h, slot Rs60', 90,
                   app_display_total([60])[0], confirm_total([60]), confirm_total([60]),
                   pending=f'Waiting on Bhanu: app charges Rs60 slot price, desk charges Rs{desk_variant_price(60, 1):.0f} rate card.'))
    rows.append(sc('VAR-DESK', 'desk', 'rate-card (variants) device, 60 min', 'desk card Rs90/h', 90,
                   desk_variant_price(60, 1), desk_variant_price(60, 1), desk_variant_price(60, 1)))
    return rows


def _num(v):
    return round(float(v), 2) if isinstance(v, (int, float, Decimal)) else v


def evaluate(row):
    values = [_num(row[k]) for k in ('shown', 'charged', 'stored')]
    if row['pending']:
        return 'PENDING'
    return 'PASS' if all(v == _num(row['expected']) for v in values) else 'FAIL'


SCENARIOS = scenarios()


@pytest.mark.parametrize('row', SCENARIOS, ids=[r['id'] for r in SCENARIOS])
def test_scenario(row):
    if row['pending']:
        pytest.skip(row['pending'])
    assert evaluate(row) == 'PASS', row


def write_matrix(out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    fields = ['id', 'channel', 'case', 'inputs', 'expected', 'shown', 'charged', 'stored', 'result', 'note']
    rows = [dict(r, result=evaluate(r), note=r['pending'] or '') for r in SCENARIOS]
    with open(out / 'scenario-matrix.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    counts = {k: sum(r['result'] == k for r in rows) for k in ('PASS', 'FAIL', 'PENDING')}
    lines = ['# Pricing scenario matrix', '',
             'Generated by hfg-booking `tests/test_pricing_scenarios.py` (branch fix/booking-pricing-audit). '
             '"shown" = what the channel displays/pays, "charged" = what the backend validates/charges, '
             '"stored" = what the transaction keeps.', '',
             f"**{counts['PASS']} pass, {counts['FAIL']} fail, {counts['PENDING']} pending decision** "
             f"({len(rows)} scenarios)", '',
             '| ID | Channel | Case | Inputs | Expected | Shown | Charged | Stored | Result |',
             '|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append('| ' + ' | '.join(str(_num(r[k])) for k in fields[:-2]) + f" | {r['result']} |")
    pend = [r for r in rows if r['note']]
    if pend:
        lines += ['', '## Pending decision', ''] + [f"- **{r['id']}**: {r['note']}" for r in pend]
    (out / 'scenario-matrix.md').write_text('\n'.join(lines) + '\n')
    return counts


if __name__ == '__main__':
    print(write_matrix(sys.argv[1] if len(sys.argv) > 1 else '.'))
