"""Flex-start bookings against a disposable PostgreSQL schema.

Run with FLEX_TEST_URI (or DESK_TEST_URI) pointing at a throwaway database,
e.g. postgresql://postgres@127.0.0.1:55432/flextest. Never a shared database.
"""
import importlib.util
import os
import sys
import threading
import types
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
D = datetime.now(IST).date() + timedelta(days=1)   # always a future day: windows are "upcoming"
D2 = D + timedelta(days=1)

SCHEMA = """
CREATE TABLE vendors(id integer primary key);
CREATE TABLE cafe_passes(id integer);
CREATE TABLE available_games(id integer primary key, vendor_id integer, game_name text, single_slot_price integer, total_slot integer);
CREATE TABLE slots(id integer primary key, gaming_type_id integer, start_time time, end_time time, available_slot integer, is_available boolean);
CREATE TABLE vendor_1_slot(vendor_id integer, date date, slot_id integer, available_slot integer, is_available boolean,
  PRIMARY KEY(vendor_id, date, slot_id));
CREATE TABLE consoles(id integer primary key, vendor_id integer, model_number text, console_number integer);
CREATE TABLE available_game_console(available_game_id integer, console_id integer);
CREATE TABLE maintenance_status(console_id integer, available_status text);
CREATE TABLE hardware_specifications(console_id integer, screen_size_inches integer);
CREATE TABLE bookings(id serial primary key, user_id integer, game_id integer, slot_id integer, status text, squad_details json);
CREATE TABLE transactions(id serial primary key, booking_id integer, booked_date date);
CREATE TABLE vendor_1_dashboard(book_id integer, user_id integer, game_id integer, console_id integer, book_status text,
  date date, start_time time, end_time time);
CREATE TABLE cafe_play_sessions(console_claim integer, started_at timestamp, created_at timestamp, ends_at timestamp,
  booking_end timestamp, deadline timestamp, minutes integer);
CREATE TABLE cafe_slot_reservations(session_id varchar(36) NOT NULL, vendor_id integer NOT NULL, date date NOT NULL,
  slot_id integer NOT NULL, units integer NOT NULL CHECK (units > 0), released_at timestamp,
  PRIMARY KEY(session_id, vendor_id, date, slot_id));
INSERT INTO vendors VALUES (1), (2);
INSERT INTO available_games VALUES (1, 1, 'PC', 100, 2), (2, 2, 'PC', 100, 1);
INSERT INTO consoles VALUES (11, 1, 'PC 1', 1), (12, 1, 'PC 2', 2), (21, 2, 'Other cafe', 1);
INSERT INTO available_game_console VALUES (1, 11), (1, 12), (2, 21);
"""


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture
def env(monkeypatch):
    uri = os.getenv("FLEX_TEST_URI") or os.getenv("DESK_TEST_URI")
    if not uri:
        pytest.skip("FLEX_TEST_URI is required for isolated PostgreSQL integration tests")
    schema = "flex_test_" + uuid.uuid4().hex
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri,
                      SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"options": f"-csearch_path={schema}"}})
    db = SQLAlchemy(app)
    for name in ("services", "controllers"):
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(ROOT / name)]
        monkeypatch.setitem(sys.modules, name, pkg)
    for name in ("services.flex_booking", "services.flex_timing", "services.slot_capacity", "services.desk_pricing",
                 "controllers.desk_operations", "controllers.flex_booking_controller"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "db", _module("db", __path__=[]))
    monkeypatch.setitem(sys.modules, "db.extensions", _module("db.extensions", db=db))
    monkeypatch.setitem(sys.modules, "services.vendor_access",
                        _module("services.vendor_access", require_vendor_permission=lambda *a: (lambda f: f)))
    monkeypatch.setitem(sys.modules, "utils", _module("utils", __path__=[]))
    events = []
    monkeypatch.setitem(sys.modules, "utils.realtime",
                        _module("utils.realtime", emit_vendor_event=lambda s, e, d, v: events.append((e, d))))
    # Pricing helpers of the desk booking controller (real ones need the whole ORM).
    monkeypatch.setitem(sys.modules, "controllers.booking_controller", _module(
        "controllers.booking_controller",
        get_effective_price_for_schedule=lambda vendor, game, day, slot=None: float(game.single_slot_price),
        _requires_multi_console_units=lambda name, vendor_id=None: str(name).upper() == "PC",
        _resolve_squad_pricing_mode=lambda name, vendor_id=None: "squad_discount",
        _resolve_squad_discount_percent=lambda name, n, policy=None, vendor_id=None: 10.0 if n > 1 else 0.0,
        _load_squad_pricing_policy=lambda vendor_id, supported_groups=None: {},
    ))
    spec = importlib.util.spec_from_file_location("controllers.flex_booking_controller",
                                                  ROOT / "controllers/flex_booking_controller.py")
    controller = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, controller)
    spec.loader.exec_module(controller)
    app.register_blueprint(controller.flex_blueprint, url_prefix="/api")
    with app.app_context():
        db.session.execute(text(f"CREATE SCHEMA {schema}"))
        db.session.execute(text(SCHEMA))
        rows = []
        for hour in range(24):
            sid = 100 + hour
            db.session.execute(text("INSERT INTO slots VALUES(:id,1,:s,:e,2,true)"),
                               {"id": sid, "s": time(hour), "e": time((hour + 1) % 24)})
            for day in (D, D2):
                rows.append({"d": day, "s": sid})
        db.session.execute(text("INSERT INTO vendor_1_slot VALUES(1,:d,:s,2,true)"), rows)
        db.session.commit()
        db.session.execute(text((ROOT / "sql/20261126_flex_start_bookings.sql").read_text()))
        db.session.commit()
        import services.flex_booking as service
        service._schema_ready = False
        yield types.SimpleNamespace(app=app, db=db, client=app.test_client(), controller=controller,
                                    service=service, events=events, schema=schema, uri=uri)
        db.session.rollback()
        db.session.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        db.session.commit()
        db.session.remove()
        db.engine.dispose()


def enable(e, **overrides):
    body = dict(flex_enabled=True, **overrides)
    response = e.client.put("/api/vendor/1/flex-booking/settings", json=body)
    assert response.status_code == 200, response.json
    return response.json["settings"]


def iso(day, h, m=0):
    return datetime.combine(day, time(h, m)).replace(tzinfo=IST).isoformat()


def quote(e, h, m, minutes, day=D, **extra):
    return e.client.post("/api/vendor/1/flex-booking/quote",
                         json=dict(gameId=1, startAt=iso(day, h, m), durationMinutes=minutes, **extra))


def available(e, hour, day=D):
    return e.db.session.execute(text("SELECT available_slot FROM vendor_1_slot WHERE date=:d AND slot_id=:s"),
                                {"d": day, "s": 100 + hour}).scalar()


def create_flex(e, h, m, minutes, consoles=None, day=D, units=1, user=7, status="upcoming"):
    """What newBooking does for timingMode=flex, minus payments: lock, pick, reserve, hold, dashboard row."""
    s, ft = e.service, sys.modules["services.flex_timing"]
    from services.slot_capacity import reserve_slot
    settings = s.load_settings(1)
    start = datetime.combine(day, time(h, m))
    plan, _ = s.plan_window(1, 1, start, minutes, settings, units)
    s.lock_consumed(1, plan.consumed, units)
    ids, _ = s.pick_consoles(1, 1, plan, units, consoles)
    reserve_slot(e.db.session, 1, plan.base.slot_id, plan.base.day, units)
    bid = e.db.session.execute(text("""INSERT INTO bookings(user_id,game_id,slot_id,status,squad_details)
        VALUES(:u,1,:s,'confirmed',CAST(:d AS json)) RETURNING id"""),
        {"u": user, "s": plan.base.slot_id,
         "d": '{"slot_units": %d, "booked_date": "%s", "assigned_console_ids": %s}' % (units, plan.base.day, ids)}).scalar()
    e.db.session.execute(text("INSERT INTO transactions(booking_id,booked_date) VALUES(:b,:d)"), {"b": bid, "d": plan.base.day})
    s.hold_extra(1, bid, plan.extra, units)
    s.write_timing(bid, plan.start, plan.end)
    e.db.session.execute(text("""INSERT INTO vendor_1_dashboard VALUES(:b,:u,1,:c,:st,:d,:s,:e)"""),
                         {"b": bid, "u": user, "c": ids[0], "st": status, "d": plan.start.date(),
                          "s": plan.start.time(), "e": plan.end.time()})
    e.db.session.commit()
    return bid, ids, plan


def slot_booking(e, hour, console=11, user=8, day=D):
    """A legacy app/desk slot booking: base slot reserved, dashboard row with the slot window."""
    from services.slot_capacity import reserve_slot
    reserve_slot(e.db.session, 1, 100 + hour, day, 1)
    bid = e.db.session.execute(text("""INSERT INTO bookings(user_id,game_id,slot_id,status,squad_details)
        VALUES(:u,1,:s,'confirmed',CAST(:d AS json)) RETURNING id"""),
        {"u": user, "s": 100 + hour, "d": '{"slot_units": 1, "booked_date": "%s"}' % day}).scalar()
    e.db.session.execute(text("INSERT INTO transactions(booking_id,booked_date) VALUES(:b,:d)"), {"b": bid, "d": day})
    e.db.session.execute(text("INSERT INTO vendor_1_dashboard VALUES(:b,:u,1,:c,'upcoming',:d,:s,:e)"),
                         {"b": bid, "u": user, "c": console, "d": day, "s": time(hour), "e": time((hour + 1) % 24)})
    e.db.session.commit()
    return bid


# Scenario 12: disabled cafes are refused with a clear code; defaults are off.
def test_flex_disabled_by_default_and_refused(env):
    got = env.client.get("/api/vendor/1/flex-booking/settings").json
    assert got["settings"]["flex_enabled"] is False and got["schema_ready"] is True
    response = quote(env, 10, 12, 120)
    assert response.status_code == 403 and response.json["code"] == "flex_disabled"
    assert env.client.put("/api/vendor/1/flex-booking/settings", json={"step_minutes": 0}).status_code == 400


def test_missing_migration_refuses_flex_but_reads_defaults(env):
    env.db.session.execute(text("DROP TABLE vendor_flex_booking_settings"))
    env.db.session.commit()
    env.service._schema_ready = False
    assert env.client.get("/api/vendor/1/flex-booking/settings").json["schema_ready"] is False
    response = quote(env, 10, 12, 120)
    assert response.status_code == 503 and response.json["code"] == "migration_required"
    assert env.service.release_holds(1, 999) == 0   # cancel paths stay no-ops


# Scenario 1 + 11: walk-in 10:12 x 2h, IST/UTC inputs agree.
def test_quote_walk_in_window_slots_price_and_stations(env):
    enable(env)
    body = quote(env, 10, 12, 120).json
    assert body["window"]["label"] == "10:12 – 12:12" and body["window"]["end_at"] == iso(D, 12, 12)
    assert [s["start_time"] for s in body["blocked_slots"]] == ["10:00", "11:00", "12:00"]
    assert body["base_slot_id"] == 110 and body["booked_date"] == D.isoformat()
    assert body["price"]["basis"] == "slot_prorated" and body["price"]["net_amount"] == 200.0
    assert body["available"] and body["recommended_console_ids"] == [11]
    utc = datetime.combine(D, time(10, 12)).replace(tzinfo=IST).astimezone(ZoneInfo("UTC")).isoformat()
    again = env.client.post("/api/vendor/1/flex-booking/quote",
                            json=dict(gameId=1, startAt=utc, durationMinutes=120)).json
    assert again["window"] == body["window"]
    assert env.client.post("/api/vendor/1/flex-booking/quote",
                           json=dict(gameId=2, startAt=utc, durationMinutes=120)).status_code == 404


# Scenario 2: station busy later -> max minutes + other station suggested.
def test_station_with_later_booking_suggests_other_station_and_max_minutes(env):
    enable(env)
    slot_booking(env, 12, console=11)
    body = quote(env, 10, 12, 120).json
    by_id = {s["console_id"]: s for s in body["stations"]}
    assert by_id[11]["available"] is False and by_id[11]["max_minutes_available"] == 108
    assert by_id[12]["available"] is True and body["recommended_console_ids"] == [12]
    with pytest.raises(sys.modules["services.flex_timing"].FlexError) as err:
        create_flex(env, 10, 12, 120, consoles=[11])
    assert err.value.code == "station_busy"
    env.db.session.rollback()
    bid, ids, _ = create_flex(env, 10, 12, 108, consoles=[11])
    assert ids == [11]


# Scenario 1 (create) + 3: capacity on every slot; back-to-back allowed; overlap refused.
def test_create_consumes_slots_back_to_back_ok_overlap_refused(env):
    enable(env)
    bid, ids, plan = create_flex(env, 10, 12, 120, consoles=[11])
    assert [available(env, h) for h in (10, 11, 12, 13)] == [1, 1, 1, 2]
    holds = env.db.session.execute(text("SELECT slot_id,units FROM cafe_slot_reservations WHERE session_id=:s ORDER BY slot_id"),
                                   {"s": f"flex:{bid}"}).all()
    assert [tuple(r) for r in holds] == [(111, 1), (112, 1)]
    timing = env.service.timing_for([bid])[bid]
    assert timing["start_at"] == iso(D, 10, 12) and timing["duration_minutes"] == 120
    second, _, _ = create_flex(env, 12, 12, 48, consoles=[11])
    assert available(env, 12) == 0
    FlexError = sys.modules["services.flex_timing"].FlexError
    with pytest.raises(FlexError):
        create_flex(env, 11, 0, 30, consoles=[11])
    env.db.session.rollback()


# Scenario 4: a slot booking still fits while capacity remains, refused when full; counts stay exact.
def test_slot_bookings_share_capacity_with_flex_windows(env):
    enable(env)
    create_flex(env, 10, 12, 120, consoles=[11])
    slot_booking(env, 12, console=12)                  # last unit of 12:00
    from services.slot_capacity import reserve_slot
    with pytest.raises(ValueError):
        reserve_slot(env.db.session, 1, 112, D, 1)
    env.db.session.rollback()
    assert available(env, 13) == 2
    held = env.db.session.execute(text("""SELECT slot_id, SUM(units) FROM cafe_slot_reservations
        WHERE vendor_id=1 AND released_at IS NULL GROUP BY slot_id ORDER BY slot_id""")).all()
    assert [tuple(r) for r in held] == [(111, 1), (112, 1)]   # what the slot grid's repair floor counts
    body = quote(env, 11, 30, 60).json
    assert body["success"] is False and body["code"] == "slot_full" and body["max_minutes"] == 30


# Scenario 5: extension = contiguous flex window on the same station, marginal price, partial offer.
def test_extension_quote_marginal_price_and_conflict_offer(env):
    enable(env)
    bid, _, _ = create_flex(env, 10, 12, 60, consoles=[11])
    body = quote(env, 11, 12, 30, extendsBookingId=bid).json
    assert body["extends_booking_id"] == bid and [s["console_id"] for s in body["stations"]] == [11]
    assert body["price"]["net_amount"] == 50.0           # 90 billed minutes - 60 already paid
    gap = quote(env, 11, 20, 30, extendsBookingId=bid)
    assert gap.status_code == 409 and gap.json["code"] == "extension_gap"
    slot_booking(env, 12, console=11, user=9)
    blocked = quote(env, 11, 12, 60, extendsBookingId=bid).json
    assert blocked["available"] is False and blocked["stations"][0]["max_minutes_available"] == 48


# Scenario 6: early end / cancel releases every hold; legacy bookings are untouched no-ops.
def test_release_holds_returns_units_once(env):
    enable(env)
    bid, _, _ = create_flex(env, 10, 12, 120, consoles=[11])
    assert env.service.release_holds(1, bid) == 2
    assert env.service.release_holds(1, bid) == 0
    env.db.session.commit()
    assert [available(env, h) for h in (10, 11, 12)] == [1, 2, 2]   # base slot is released by the legacy path
    legacy = slot_booking(env, 15)
    assert env.service.release_holds(1, legacy) == 0


# Scenarios 7 and 8: arrival re-timing.
def test_late_arrival_keep_end_and_shift_if_free(env):
    enable(env)
    bid = slot_booking(env, 11, console=11)
    response = env.client.post(f"/api/vendor/1/flex-booking/{bid}/arrival",
                               json=dict(arrivedAt=iso(D, 11, 20), policy="keep_end"))
    assert response.status_code == 200, response.json
    assert response.json["end_at"] == iso(D, 12) and response.json["added_slots"] == []
    row = env.db.session.execute(text("SELECT start_time,end_time FROM vendor_1_dashboard WHERE book_id=:b"), {"b": bid}).first()
    assert tuple(row) == (time(11, 20), time(12))

    late = slot_booking(env, 14, console=12, user=10)
    shifted = env.client.post(f"/api/vendor/1/flex-booking/{late}/arrival",
                              json=dict(arrivedAt=iso(D, 14, 20), policy="shift_if_free")).json
    assert shifted["end_at"] == iso(D, 15, 20) and shifted["added_slots"] == [{"slot_id": 115, "date": D.isoformat()}]
    assert available(env, 15) == 1 and shifted["price_change"] == 0.0


def test_shift_refused_when_station_has_next_booking(env):
    enable(env, late_arrival_policy="shift_if_free")
    bid = slot_booking(env, 11, console=11)
    slot_booking(env, 12, console=11, user=9)
    response = env.client.post(f"/api/vendor/1/flex-booking/{bid}/arrival", json=dict(arrivedAt=iso(D, 11, 20)))
    assert response.status_code == 409 and response.json["code"] == "station_busy"
    assert available(env, 12) == 1                     # nothing held after the refusal


def test_early_arrival_starts_early_when_station_free(env):
    enable(env)
    bid = slot_booking(env, 11, console=11)
    body = env.client.post(f"/api/vendor/1/flex-booking/{bid}/arrival", json=dict(arrivedAt=iso(D, 10, 45))).json
    assert (body["start_at"], body["end_at"]) == (iso(D, 10, 45), iso(D, 11, 45))
    assert body["added_slots"] == [{"slot_id": 110, "date": D.isoformat()}] and available(env, 10) == 1


# Scenario 9: overnight windows hold slots on both dates; closing time without a 24h grid.
def test_overnight_window_and_closing(env):
    enable(env)
    bid, _, plan = create_flex(env, 23, 30, 120, consoles=[12])
    assert plan.base.day == D and available(env, 23) == 1
    assert [available(env, h, D2) for h in (0, 1, 2)] == [1, 1, 2]
    env.db.session.execute(text("DELETE FROM vendor_1_slot WHERE date=:d"), {"d": D2})
    env.db.session.commit()
    body = quote(env, 23, 0, 120).json
    assert body["code"] == "too_long" and body["max_minutes"] == 60
    enable(env, allow_past_closing=True)
    assert quote(env, 23, 0, 120).json["success"] is True


# Scenario 10: squads hold one station per player and are priced per player.
def test_squad_needs_two_stations_and_two_units(env):
    enable(env)
    body = quote(env, 10, 12, 120, players=2).json
    assert body["units"] == 2 and body["recommended_console_ids"] == [11, 12]
    assert body["price"]["base_amount"] == 400.0 and body["price"]["squad_discount_amount"] == 40.0
    create_flex(env, 10, 12, 120, consoles=[11, 12], units=2)
    assert [available(env, h) for h in (10, 11, 12)] == [0, 0, 0]


def test_rate_card_prices_exact_duration(env):
    for name in ("20261103_desk_rates_and_history.sql", "20261108_unified_pricing.sql", "20261109_custom_desk_pricing.sql"):
        env.db.session.execute(text((ROOT / "sql" / name).read_text()))
        env.db.session.commit()
    definition = ('{"name":"PC","model_name":"Std","game_variant":"","screen_size_inches":null,"controllers_included":false,'
                  '"console_ids":[],"rules":[{"min_minutes":1,"max_minutes":null,"min_players":1,"max_players":8,'
                  '"amount":"90","unit_minutes":60,"per_player":true}]}')
    env.db.session.execute(text("""INSERT INTO desk_rate_cards(vendor_id,game_id,profile,rates,definition,is_active)
        VALUES(1,1,'std','[]'::jsonb,CAST(:d AS jsonb),true)"""), {"d": definition})
    env.db.session.execute(text("INSERT INTO desk_pricing_settings(vendor_id,game_id,mode) VALUES(1,1,'variants')"))
    env.db.session.commit()
    enable(env)
    body = quote(env, 10, 12, 100, deskProfile="std").json
    assert body["price"]["basis"] == "rate_card" and body["price"]["net_amount"] == 150.0   # 90 * 100/60


# Scenario 15: two simultaneous requests for the last unit -> exactly one wins.
def test_concurrent_requests_for_last_unit(env):
    enable(env)
    env.db.session.execute(text("UPDATE vendor_1_slot SET available_slot=1 WHERE date=:d AND slot_id=112"), {"d": D})
    env.db.session.commit()
    barrier = threading.Barrier(2)
    results = []

    def attempt(console):
        with env.app.app_context():
            try:
                barrier.wait()
                create_flex(env, 11, 30, 60, consoles=[console], user=console)
                results.append("ok")
            except Exception as exc:   # FlexError/ValueError from the losing transaction
                env.db.session.rollback()
                results.append(type(exc).__name__)
            finally:
                env.db.session.remove()

    threads = [threading.Thread(target=attempt, args=(c,)) for c in (11, 12)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert sorted(results) == ["FlexError", "ok"]
    assert available(env, 12) == 0 and available(env, 11) == 1
