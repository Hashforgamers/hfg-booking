"""Scenario 13: slot bookings take exactly the old path when timingMode is absent."""
import ast
import sys
from datetime import date, time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "controllers/booking_controller.py"
FLEX_ONLY = {"flex_booking", "flex_parse", "previous_flex_booking", "flex_window_price", "flex_rules"}


def _function(path, name, cls=None):
    tree = ast.parse(path.read_text())
    body = tree.body
    if cls:
        body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == cls).body
    return next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)


def _guarded(test):
    names = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)}
    consts = {n.value for n in ast.walk(test) if isinstance(n, ast.Constant)}
    return bool(names & {"flex_plan", "flex_price", "flex_previous"}) or "timingMode" in consts


def test_every_flex_call_in_new_booking_is_behind_a_flex_guard():
    fn = _function(CONTROLLER, "new_booking")
    offenders = []

    def visit(node, guarded):
        if isinstance(node, (ast.If, ast.IfExp)) and _guarded(node.test):
            for child in node.body if isinstance(node, ast.If) else [node.body]:
                visit(child, True)
            for child in (node.orelse if isinstance(node, ast.If) else [node.orelse]):
                visit(child, guarded)
            return
        if isinstance(node, ast.Name) and node.id in FLEX_ONLY and not guarded:
            offenders.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(fn, False)
    assert offenders == [], f"flex code reachable without timingMode at lines {offenders}"
    source = ast.unparse(fn)
    assert "flex_plan = None" in source and "precheck_error = None if flex_plan else _precheck_slot_booking_eligibility(" in source


def test_release_slot_for_booking_releases_base_then_flex_holds(monkeypatch):
    node = _function(CONTROLLER, "_release_slot_for_booking")
    calls = []
    capacity = ModuleType("services.slot_capacity")
    capacity.release_slot = lambda session, vendor, slot, day, units: calls.append(("base", vendor, slot, day, units))
    capacity.booking_units = lambda details: int(details.get("slot_units", 1))
    flex = ModuleType("services.flex_booking")
    flex.release_holds = lambda vendor, booking_id: calls.append(("flex", vendor, booking_id)) or 0
    monkeypatch.setitem(sys.modules, "services.slot_capacity", capacity)
    monkeypatch.setitem(sys.modules, "services.flex_booking", flex)
    scope = dict(AvailableGame=MagicMock(), db=MagicMock(), current_app=MagicMock(),
                 _requires_multi_console_units=lambda *a, **k: False)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(CONTROLLER), "exec"), scope)
    booking = SimpleNamespace(id=5, slot_id=110, squad_details={"slot_units": 1}, game=SimpleNamespace(game_name="PS5"))
    assert scope["_release_slot_for_booking"](booking, 1, date(2026, 11, 26)) is True
    assert calls == [("base", 1, 110, date(2026, 11, 26), 1), ("flex", 1, 5)]


def test_dashboard_rows_keep_slot_window_unless_a_flex_window_is_given():
    node = _function(ROOT / "services/booking_service.py", "insert_vendor_booking_rows", cls="BookingService")
    node.decorator_list = []
    db = MagicMock()
    scope = dict(db=db, text=lambda sql: sql)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "booking_service", "exec"), scope)
    slot = SimpleNamespace(start_time=time(10), end_time=time(11))
    booking = SimpleNamespace(id=1, slot_id=110, game_id=1, status="confirmed")
    tx = SimpleNamespace(id=9, booking_id=1, booked_date=date(2026, 11, 26), amount=100)
    args = (1, [tx], [booking], SimpleNamespace(id=3, name="Asha"), SimpleNamespace(game_name="PC"), {110: slot})
    scope["insert_vendor_booking_rows"](*args, {1: {"dashboard_status": "upcoming", "console_id": -1}})
    legacy = db.session.execute.call_args_list[0].args[1][0]
    assert (legacy["start_time"], legacy["end_time"], legacy["date"]) == (time(10), time(11), date(2026, 11, 26))
    db.reset_mock()
    meta = {"dashboard_status": "upcoming", "console_id": 11, "date": date(2026, 11, 27),
            "start_time": time(0, 10), "end_time": time(2, 10)}
    scope["insert_vendor_booking_rows"](*args, {1: meta})
    flex = db.session.execute.call_args_list[0].args[1][0]
    assert (flex["start_time"], flex["end_time"], flex["date"], flex["console_id"]) == (time(0, 10), time(2, 10), date(2026, 11, 27), 11)


def test_flex_blueprint_is_registered_and_routes_are_new():
    init = (ROOT / "app/__init__.py").read_text()
    assert "register_blueprint(flex_blueprint, url_prefix='/api')" in init
    flex = (ROOT / "controllers/flex_booking_controller.py").read_text()
    for route in ("/vendor/<int:vendor_id>/flex-booking/settings", "/vendor/<int:vendor_id>/flex-booking/quote",
                  "/vendor/<int:vendor_id>/flex-booking/<int:booking_id>/arrival"):
        assert route in flex
    existing = CONTROLLER.read_text() + (ROOT / "controllers/slot_controller.py").read_text()
    assert "flex-booking" not in existing
