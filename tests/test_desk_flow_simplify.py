"""Desk flow: deterministic prices, early release returns, assign-the-station-later bookings."""
import json
import os
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import early_release as er  # noqa: E402  (pure imports only)


# ------------------------------------------------------------ pure pricing rules

def test_unused_value_is_pro_rata_on_paid_whole_rupees_and_deterministic():
    # 1h45m PC paid Rs 175, ended after 60 min: 45 min unused -> Rs 75, every time.
    assert er.unused_value(175, 105, 45) == 75
    assert {er.unused_value(175, 105, 45) for _ in range(50)} == {75}
    # Half up to whole rupees: 175 * 10 / 105 = 16.67 -> 17.
    assert er.unused_value(175, 105, 10) == 17
    # Under the minimum (default 5 min): nothing. The minimum is the cafe's setting.
    assert er.unused_value(175, 105, 4) == 0
    assert er.unused_value(175, 105, 4, min_unused=0) == 7
    # Never more than what was paid, nothing for free or pass sessions.
    assert er.unused_value(175, 105, 500) == 175
    assert er.unused_value(0, 105, 45) == 0


def test_gaming_amounts_use_what_was_paid_after_discounts_not_food_or_extras():
    lines = [
        # Rs 175 rate card, Rs 20 staff discount, Rs 40 food on the same line.
        {"booking_type": "direct", "settlement_status": "completed", "amount": 195, "meals_amount": 40,
         "controller_amount": 0, "mode_of_payment": "UPI"},
        {"booking_type": "extra", "settlement_status": "completed", "amount": 50, "mode_of_payment": "cash"},
        {"booking_type": "additional_meals", "settlement_status": "pending", "amount": 30},
        {"booking_type": "settlement_waive_off", "settlement_status": "completed", "amount": -10},
        {"booking_type": "early_release_credit", "settlement_status": "completed", "amount": -60},
        {"booking_type": "direct", "settlement_status": "cancelled", "amount": 999},
    ]
    paid, pending, method = er.gaming_amounts(lines)
    assert (paid, pending, method) == (155.0, 0.0, "upi")
    assert er.refund_method_for(method) == "upi"
    unpaid = [{"booking_type": "pay_at_cafe", "settlement_status": "pending", "amount": 120}]
    assert er.gaming_amounts(unpaid) == (0.0, 120.0, None)


def test_breakdown_minutes_threshold_and_policies():
    start = datetime(2026, 11, 27, 1, 33)
    end = start + timedelta(minutes=105)
    settings = er.default_settings()
    ended = start + timedelta(minutes=60, seconds=40)  # play rounds down: 60 min played
    got = er.breakdown(start, end, 105 * 60, ended, 175.0, 0.0, settings)
    assert (got["played_minutes"], got["unused_minutes"], got["return_amount"], got["eligible"]) == (60, 45, 75, True)
    # Ended at (or after) the booked end: nothing unused.
    assert er.breakdown(start, end, 105 * 60, end + timedelta(minutes=3), 175.0, 0, settings)["return_amount"] == 0
    # 3 minutes early with the default 5-minute minimum: not eligible.
    late = er.breakdown(start, end, 105 * 60, end - timedelta(minutes=3), 175.0, 0, settings)
    assert (late["unused_minutes"], late["eligible"], late["return_amount"]) == (3, False, 0)
    # Pay-later gaming is reduced instead of returned.
    unpaid = er.breakdown(start, end, 105 * 60, ended, 0.0, 175.0, settings)
    assert (unpaid["return_amount"], unpaid["pending_reduction"]) == (0, 75)
    # "No return" cafes: the PC is just freed.
    none = er.breakdown(start, end, 105 * 60, ended, 175.0, 175.0, {"policy": "none", "min_unused_minutes": 5})
    assert (none["return_amount"], none["pending_reduction"]) == (0, 0)


def test_policy_settings_validation_and_modes():
    assert er.default_settings() == {"policy": "credit_default", "min_unused_minutes": 5}
    assert er.allowed_modes("credit_default") == ("credit", "refund")
    assert er.default_mode("refund") == "refund" and er.allowed_modes("none") == ("none",)
    assert er.normalize_settings({"policy": "credit", "min_unused_minutes": 10}) == {"policy": "credit", "min_unused_minutes": 10}
    for bad in ({"policy": "cash"}, {"min_unused_minutes": 61}, {"min_unused_minutes": "x"}, {"min_unused_minutes": True}):
        with pytest.raises(er.EarlyReleaseError):
            er.normalize_settings(bad)


# ------------------------------------------------------------ early release on PostgreSQL

SCHEMA = """
CREATE TABLE vendors(id integer primary key);
INSERT INTO vendors VALUES (1);
CREATE TABLE users(id integer primary key, name text);
INSERT INTO users VALUES (7, 'Asha');
CREATE TABLE bookings(id integer primary key, user_id integer, game_id integer, slot_id integer, status text, squad_details json);
CREATE TABLE vendor_1_dashboard(book_id integer, user_id integer, game_id integer, console_id integer, book_status text,
  date date, start_time time, end_time time);
CREATE TABLE transactions(id serial primary key, booking_id integer, vendor_id integer, user_id integer, booked_date date,
  booking_date date, booking_time time, user_name text, original_amount float, discounted_amount float, amount float,
  mode_of_payment text, payment_use_case text, booking_type text, settlement_status text, source_channel text,
  initiated_by_staff_id text, initiated_by_staff_name text, initiated_by_staff_role text, base_amount float default 0,
  meals_amount float default 0, controller_amount float default 0, waive_off_amount float default 0,
  app_fee_amount float default 0, taxable_amount float default 0, gst_rate float default 0, cgst_amount float default 0,
  sgst_amount float default 0, igst_amount float default 0, total_with_tax float default 0, reference_id text,
  created_at timestamp, updated_at timestamp);
CREATE TABLE cafe_wallets(vendor_id integer, user_id integer, balance bigint, reserved bigint, PRIMARY KEY(vendor_id, user_id),
  CHECK (balance >= 0 AND reserved >= 0 AND balance >= reserved));
CREATE TABLE cafe_wallet_ledger(id serial PRIMARY KEY, vendor_id integer, user_id integer, kind text, amount bigint,
  balance_after bigint, reserved_after bigint, actor_id text, actor_name text, method text, reason text,
  idempotency_key text, fingerprint text, created_at timestamp, UNIQUE(vendor_id, idempotency_key));
"""
DAY = datetime(2026, 11, 27).date()
NOW = datetime(2026, 11, 27, 2, 33)  # one hour into a 01:33-03:18 session


@pytest.fixture
def db():
    url = os.getenv("CAFE_TEST_DATABASE_URL") or os.getenv("DESK_TEST_URI")
    if not url:
        pytest.skip("Disposable PostgreSQL required (CAFE_TEST_DATABASE_URL)")
    engine = create_engine(url)
    schema = "early_release_" + uuid.uuid4().hex
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))

    def checkout(conn, *a):
        with conn.cursor() as cursor:
            cursor.execute(f"SET search_path TO {schema}")
        conn.commit()
    event.listen(engine, "checkout", checkout)
    with engine.begin() as c:
        c.execute(text(SCHEMA))
        c.execute(text((ROOT / "sql/20261127_unused_time_policy.sql").read_text()))
    session = scoped_session(sessionmaker(bind=engine))
    yield session
    session.remove()
    event.remove(engine, "checkout", checkout)
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    engine.dispose()


def flex_session(s, bid=501, paid=175.0, status="completed", method="UPI", meals=0.0):
    s.execute(text("INSERT INTO bookings VALUES(:b,7,1,100,'checked_in',CAST(:d AS json))"),
              {"b": bid, "d": json.dumps({"timing_mode": "flex"})})
    s.execute(text("INSERT INTO vendor_1_dashboard VALUES(:b,7,1,11,'current',:d,:s,:e)"),
              {"b": bid, "d": DAY, "s": time(1, 33), "e": time(3, 18)})
    s.execute(text("""INSERT INTO transactions(booking_id,vendor_id,user_id,user_name,amount,original_amount,meals_amount,
        base_amount,mode_of_payment,booking_type,settlement_status,total_with_tax)
        VALUES(:b,1,7,'Asha',:a,:a,:m,:a,:mode,'direct',:st,:a)"""),
              {"b": bid, "a": paid + meals, "m": meals, "mode": method, "st": status})
    s.commit()
    return SimpleNamespace(id=bid, user_id=7)


def test_early_release_credit_goes_to_cafe_wallet_once_with_audit_rows(db):
    booking = flex_session(db, meals=40.0)
    quote = er.quote(db, 1, booking, console_id=11, now=NOW)
    assert (quote["booked_minutes"], quote["played_minutes"], quote["unused_minutes"]) == (105, 60, 45)
    assert (quote["paid_amount"], quote["return_amount"], quote["default_mode"]) == (175.0, 75, "credit")
    record = er.apply(db, 1, booking, console_id=11, now=NOW, actor={"staff_name": "Ravi", "source_channel": "dashboard"})
    db.commit()
    assert (record["mode"], record["amount"]) == ("credit", 75)
    assert db.execute(text("SELECT balance FROM cafe_wallets WHERE user_id=7")).scalar() == 7500
    ledger = db.execute(text("SELECT kind,amount,method FROM cafe_wallet_ledger")).all()
    assert [tuple(r) for r in ledger] == [("adjustment", 7500, "early_release")]
    tx = db.execute(text("""SELECT amount,booking_type,mode_of_payment,settlement_status FROM transactions
        WHERE booking_type LIKE 'early_release%'""")).all()
    assert [tuple(r) for r in tx] == [(-75.0, "early_release_credit", "cafe_wallet", "completed")]
    details = db.execute(text("SELECT squad_details FROM bookings WHERE id=501")).scalar()
    assert details["early_release"]["unused_minutes"] == 45 and details["timing_mode"] == "flex"
    # A second click (or a retry after a network error) records nothing new.
    again = er.apply(db, 1, booking, console_id=11, now=NOW + timedelta(minutes=5))
    db.commit()
    assert again["already_recorded"] is True and again["amount"] == 75
    assert db.execute(text("SELECT count(*) FROM transactions WHERE booking_type LIKE 'early_release%'")).scalar() == 1
    assert db.execute(text("SELECT balance FROM cafe_wallets WHERE user_id=7")).scalar() == 7500


def test_early_release_refund_and_policy_switch(db):
    booking = flex_session(db)
    with pytest.raises(er.EarlyReleaseError):
        er.apply(db, 1, booking, mode="refund", refund_method="cheque", now=NOW)
    db.rollback()
    record = er.apply(db, 1, booking, mode="refund", now=NOW)
    db.commit()
    assert (record["mode"], record["refund_method"], record["amount"]) == ("refund", "upi", 75)
    assert db.execute(text("SELECT count(*) FROM cafe_wallet_ledger")).scalar() == 0

    other = flex_session(db, bid=502)
    db.execute(text("UPDATE vendor_1_dashboard SET user_id=8, console_id=12 WHERE book_id=502"))
    db.execute(text("UPDATE bookings SET user_id=8 WHERE id=502"))
    db.commit()
    assert er.save_settings(db, 1, {"policy": "credit"}) == {"policy": "credit", "min_unused_minutes": 5}
    db.commit()
    with pytest.raises(er.EarlyReleaseError) as refused:
        er.apply(db, 1, SimpleNamespace(id=502, user_id=8), mode="refund", now=NOW)
    assert refused.value.status == 409
    db.rollback()
    er.save_settings(db, 1, {"policy": "none"})
    db.commit()
    record = er.apply(db, 1, SimpleNamespace(id=502, user_id=8), now=NOW)
    db.commit()
    assert (record["mode"], record["amount"]) == ("none", 0)


def test_short_or_unpaid_sessions_return_nothing(db):
    booking = flex_session(db, status="pending")
    quote = er.quote(db, 1, booking, now=NOW)
    assert (quote["return_amount"], quote["pending_reduction"]) == (0, 75)
    near_end = datetime.combine(DAY, time(3, 15))
    assert er.quote(db, 1, booking, now=near_end)["eligible"] is False
    with pytest.raises(er.EarlyReleaseError):
        er.quote(db, 1, booking, ended_at=NOW + timedelta(hours=2), now=NOW)  # cannot end in the future


def test_back_to_back_slot_bookings_are_one_session(db):
    for bid, (s, e) in zip((601, 602, 603), ((time(1, 0), time(1, 30)), (time(1, 30), time(2, 0)), (time(2, 0), time(2, 30)))):
        db.execute(text("INSERT INTO bookings VALUES(:b,7,1,100,'checked_in','{}')"), {"b": bid})
        db.execute(text("INSERT INTO vendor_1_dashboard VALUES(:b,7,1,11,'current',:d,:s,:e)"), {"b": bid, "d": DAY, "s": s, "e": e})
        db.execute(text("""INSERT INTO transactions(booking_id,vendor_id,user_id,user_name,amount,original_amount,
            mode_of_payment,booking_type,settlement_status) VALUES(:b,1,7,'Asha',50,50,'Cash','direct','completed')"""), {"b": bid})
    db.commit()
    quote = er.quote(db, 1, SimpleNamespace(id=601, user_id=7), now=datetime.combine(DAY, time(1, 45)))
    assert quote["booking_ids"] == [601, 602, 603]
    assert (quote["booked_minutes"], quote["played_minutes"], quote["paid_amount"], quote["return_amount"]) == (90, 45, 150.0, 75)
    assert quote["refund_method"] == "cash"


# ------------------------------------------------------------ assign the station at start

from test_flex_booking_db import env, enable, available, create_flex, D  # noqa: E402,F401


def create_unassigned(e, h, m, minutes, units=1, user=9):
    """newBooking with assignLater: slot units held, no station picked."""
    s = e.service
    from services.slot_capacity import reserve_slot
    plan, _ = s.plan_window(1, 1, datetime.combine(D, time(h, m)), minutes, s.load_settings(1), units)
    s.lock_consumed(1, plan.consumed, units)
    s.check_capacity(1, 1, plan, units)
    reserve_slot(e.db.session, 1, plan.base.slot_id, plan.base.day, units)
    bid = e.db.session.execute(text("""INSERT INTO bookings(user_id,game_id,slot_id,status,squad_details)
        VALUES(:u,1,:s,'confirmed',CAST(:d AS json)) RETURNING id"""),
        {"u": user, "s": plan.base.slot_id,
         "d": json.dumps({"slot_units": units, "booked_date": str(plan.base.day), "assign_later": True,
                          "assigned_console_ids": []})}).scalar()
    s.hold_extra(1, bid, plan.extra, units)
    e.db.session.execute(text("INSERT INTO vendor_1_dashboard VALUES(:b,:u,1,-1,'upcoming',:d,:s,:e)"),
                         {"b": bid, "u": user, "d": plan.start.date(), "s": plan.start.time(), "e": plan.end.time()})
    e.db.session.commit()
    return bid, plan


def test_unassigned_booking_holds_type_capacity_and_a_station(env):
    enable(env)
    env.db.session.execute(text("UPDATE vendor_1_slot SET available_slot=5"))  # more slot units than stations
    env.db.session.commit()
    before = [available(env, h) for h in (10, 11)]
    create_unassigned(env, 10, 15, 60)
    assert [available(env, h) for h in (10, 11)] == [before[0] - 1, before[1] - 1]
    assert env.service.unassigned_units(1, 1, datetime.combine(D, time(10)), datetime.combine(D, time(12)),
                                        now=datetime.combine(D, time(0))) == 1
    # One more booking can take a station for the same window...
    create_flex(env, 10, 15, 60)
    # ...but the last free station stays for the booking that gets its station at start.
    from services.flex_timing import FlexError
    with pytest.raises(FlexError) as busy:
        create_flex(env, 10, 30, 60)
    assert busy.value.code == "station_busy"
    with pytest.raises(FlexError):
        create_unassigned(env, 10, 30, 30)


def test_back_to_back_unassigned_rows_count_once(env):
    enable(env)
    for hour in (14, 15):
        env.db.session.execute(text("""INSERT INTO bookings(id,user_id,game_id,slot_id,status,squad_details)
            VALUES(:b,5,1,:s,'confirmed','{}')"""), {"b": 900 + hour, "s": 100 + hour})
        env.db.session.execute(text("INSERT INTO vendor_1_dashboard VALUES(:b,5,1,NULL,'upcoming',:d,:s,:e)"),
                               {"b": 900 + hour, "d": D, "s": time(hour), "e": time(hour + 1)})
    env.db.session.commit()
    window = (datetime.combine(D, time(14, 30)), datetime.combine(D, time(15, 30)))
    assert env.service.unassigned_units(1, 1, *window, now=datetime.combine(D, time(0))) == 1
