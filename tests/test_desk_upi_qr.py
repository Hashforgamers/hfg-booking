"""Desk UPI QR collection. Run with DESK_TEST_URI pointing at a disposable PostgreSQL database."""
import hashlib
import hmac
import importlib
import json
import os
import sys
import types
import uuid
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, g, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'desk-webhook-secret'

SCHEMA = '''
CREATE TABLE vendors(id integer primary key, cafe_name text);
CREATE TABLE available_games(id integer primary key, vendor_id integer);
CREATE TABLE bookings(id integer primary key, game_id integer);
CREATE TABLE transactions(
 id serial primary key, booking_id integer, vendor_id integer, user_id integer,
 booked_date date NOT NULL, booking_date date NOT NULL, booking_time time NOT NULL, user_name text NOT NULL,
 amount float NOT NULL, original_amount float NOT NULL, discounted_amount float NOT NULL DEFAULT 0,
 mode_of_payment text NOT NULL DEFAULT 'online', payment_use_case text, booking_type text NOT NULL DEFAULT 'booking',
 settlement_status text NOT NULL DEFAULT 'pending', source_channel text NOT NULL DEFAULT 'app',
 initiated_by_staff_id text, initiated_by_staff_name text, initiated_by_staff_role text,
 base_amount float NOT NULL DEFAULT 0, meals_amount float NOT NULL DEFAULT 0, controller_amount float NOT NULL DEFAULT 0,
 waive_off_amount float NOT NULL DEFAULT 0, app_fee_amount float NOT NULL DEFAULT 0, taxable_amount float NOT NULL DEFAULT 0,
 gst_rate float NOT NULL DEFAULT 0, cgst_amount float NOT NULL DEFAULT 0, sgst_amount float NOT NULL DEFAULT 0,
 igst_amount float NOT NULL DEFAULT 0, total_with_tax float NOT NULL DEFAULT 0, reference_id varchar(100),
 created_at timestamp, updated_at timestamp);
INSERT INTO vendors VALUES (1,'Cafe One'),(2,'Cafe Two');
INSERT INTO available_games VALUES (10,1),(20,2);
INSERT INTO bookings VALUES (100,10),(101,10),(200,20);
'''


class FakeQr:
    def __init__(self):
        self.created, self.closed, self.payments = [], [], {}

    def create(self, data):
        qid = f'qr_{len(self.created) + 1}'
        self.created.append(dict(data, id=qid))
        self.payments[qid] = []
        return {'id': qid, 'image_url': f'https://rzp.io/{qid}.png'}

    def fetch_all_payments(self, qid):
        return {'items': self.payments.get(qid, [])}

    def close(self, qid):
        self.closed.append(qid)


@pytest.fixture
def env(monkeypatch):
    uri = os.getenv('DESK_TEST_URI')
    if not uri:
        pytest.skip('DESK_TEST_URI required')
    schema = 'upiqr_' + uuid.uuid4().hex
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri, DESK_UPI_WEBHOOK_SECRET=SECRET,
                      RAZORPAY_KEY_ID='k', RAZORPAY_KEY_SECRET='s',
                      SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'options': f'-csearch_path={schema}'}})
    db = SQLAlchemy(app)
    for pkg in ('services', 'controllers'):
        mod = types.ModuleType(pkg); mod.__path__ = [str(ROOT / pkg)]; monkeypatch.setitem(sys.modules, pkg, mod)
    ext = types.ModuleType('db.extensions'); ext.db = db; monkeypatch.setitem(sys.modules, 'db.extensions', ext)

    def permission(*_):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if request.headers.get('X-Test-Vendor') != str(kwargs['vendor_id']):
                    return jsonify(error='denied'), 403
                g.vendor_claims = {'staff': {'id': 7, 'name': 'Asha', 'role': 'cashier'}}
                return fn(*args, **kwargs)
            return wrapped
        return decorate
    access = types.ModuleType('services.vendor_access'); access.require_vendor_permission = permission
    monkeypatch.setitem(sys.modules, 'services.vendor_access', access)
    for name in ('services.desk_upi_qr', 'controllers.desk_upi_qr'):
        monkeypatch.delitem(sys.modules, name, raising=False)
    service = importlib.import_module('services.desk_upi_qr')
    controller = importlib.import_module('controllers.desk_upi_qr')
    fake = FakeQr()
    monkeypatch.setattr(service, 'gateway', lambda: SimpleNamespace(qrcode=fake))
    emitted = []
    app.extensions['socketio'] = SimpleNamespace(emit=lambda *a, **k: emitted.append((a, k)))
    app.register_blueprint(controller.desk_upi_qr, url_prefix='/api')
    with app.app_context():
        db.session.execute(text(f'CREATE SCHEMA {schema}')); db.session.commit()
        db.session.execute(text(SCHEMA))
        db.session.execute(text((ROOT / 'sql/20261121_desk_upi_qr.sql').read_text()))
        db.session.commit()
    ns = SimpleNamespace(app=app, db=db, client=app.test_client(), fake=fake, emitted=emitted)
    yield ns
    with app.app_context():
        db.session.remove(); db.session.execute(text(f'DROP SCHEMA {schema} CASCADE')); db.session.commit()


def add_tx(env, booking=100, vendor=1, amount=0.0, total=0.0, kind='extra', status='pending'):
    with env.app.app_context():
        tid = env.db.session.execute(text('''INSERT INTO transactions(booking_id,vendor_id,user_id,booked_date,booking_date,booking_time,
            user_name,amount,original_amount,total_with_tax,booking_type,settlement_status)
            VALUES(:b,:v,5,current_date,current_date,current_time,'Ravi',:a,:a,:t,:k,:s) RETURNING id'''),
            dict(b=booking, v=vendor, a=amount, t=total, k=kind, s=status)).scalar()
        env.db.session.commit()
        return tid


def rows(env, sql, **params):
    with env.app.app_context():
        return [dict(r) for r in env.db.session.execute(text(sql), params).mappings()]


def create(env, vendor=1, booking=100, **body):
    return env.client.post(f'/api/vendor/{vendor}/bookings/{booking}/upi-qr', json=body, headers={'X-Test-Vendor': str(vendor)})


def status(env, cid, vendor=1):
    return env.client.get(f'/api/vendor/{vendor}/upi-qr/{cid}', headers={'X-Test-Vendor': str(vendor)})


def webhook(env, qr_id, amount, payment_id='pay_1', secret=SECRET, pstatus='captured'):
    raw = json.dumps({'event': 'qr_code.credited', 'payload': {
        'qr_code': {'entity': {'id': qr_id}},
        'payment': {'entity': {'id': payment_id, 'amount': amount, 'currency': 'INR', 'status': pstatus}}}}).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return env.client.post('/api/payments/desk-upi-webhook', data=raw, content_type='application/json',
                           headers={'X-Razorpay-Signature': sig})


def test_qr_amount_from_server_rows_with_waive_off_and_reuse(env):
    add_tx(env, amount=100, total=118, kind='extra')
    add_tx(env, amount=50, kind='additional_meals')
    add_tx(env, amount=999, kind='booking', status='completed')
    first = create(env, booking_types=['extra', 'additional_meals'], waive_off_amount=18)
    assert first.status_code == 201, first.json
    assert first.json['amount_paise'] == 15000 and first.json['status'] == 'open'
    sent = env.fake.created[0]
    assert sent['usage'] == 'single_use' and sent['fixed_amount'] and sent['payment_amount'] == 15000
    again = create(env, booking_types=['additional_meals', 'extra'], waive_off_amount=18)
    assert again.json['collection_id'] == first.json['collection_id'] and len(env.fake.created) == 1


def test_bill_change_replaces_open_qr(env):
    add_tx(env, amount=100, kind='extra')
    first = create(env, booking_types=['extra', 'additional_meals']).json
    add_tx(env, amount=40, kind='additional_meals')
    second = create(env, booking_types=['extra', 'additional_meals']).json
    assert second['collection_id'] != first['collection_id'] and second['amount_paise'] == 14000
    assert env.fake.closed == ['qr_1']
    assert rows(env, 'SELECT status FROM desk_upi_collections WHERE id=:i', i=first['collection_id'])[0]['status'] == 'closed'


def test_other_cafe_and_nothing_due_rejected(env):
    add_tx(env, booking=200, vendor=2, amount=100)
    assert create(env, vendor=1, booking=200).status_code == 404
    assert create(env, vendor=1, booking=100).status_code == 400
    assert env.client.post('/api/vendor/2/bookings/200/upi-qr', json={}, headers={'X-Test-Vendor': '1'}).status_code == 403


def test_webhook_marks_paid_to_hash_with_cafe_settlement_pending(env):
    t1 = add_tx(env, amount=100, kind='extra')
    t2 = add_tx(env, amount=60, kind='additional_meals')
    qr = create(env, booking_types=['extra', 'additional_meals'], waive_off_amount=10).json
    assert webhook(env, 'qr_1', 15000, secret='wrong').status_code == 403
    assert webhook(env, 'qr_1', 14999).status_code == 200  # Amount mismatch is ignored.
    assert status(env, qr['collection_id']).json['status'] == 'open'
    assert webhook(env, 'qr_1', 15000).status_code == 200
    assert webhook(env, 'qr_1', 15000).status_code == 200  # Replay is a no-op.
    tx = rows(env, 'SELECT id,mode_of_payment,payment_use_case,settlement_status,initiated_by_staff_name FROM transactions WHERE id IN (:a,:b) ORDER BY id', a=t1, b=t2)
    assert all(r['mode_of_payment'] == 'hash_upi_qr' and r['payment_use_case'] == 'payment_gateway'
               and r['settlement_status'] == 'completed' and r['initiated_by_staff_name'] == 'Asha' for r in tx)
    waive = rows(env, "SELECT amount FROM transactions WHERE booking_type='settlement_waive_off'")
    assert waive == [{'amount': -10.0}]
    col = rows(env, 'SELECT status,payment_id,cafe_settlement_status FROM desk_upi_collections')[0]
    assert col == {'status': 'paid', 'payment_id': 'pay_1', 'cafe_settlement_status': 'pending'}
    events = [a[1] for a, _ in env.emitted]
    assert len(events) == 1 and events[0]['event'] == 'upi_qr_paid' and events[0]['bookingId'] == 100


def test_status_poll_applies_payment_without_webhook(env):
    add_tx(env, amount=75, kind='extra')
    qr = create(env, booking_types=['extra']).json
    env.fake.payments['qr_1'].append({'id': 'pay_9', 'amount': 7500, 'currency': 'INR', 'status': 'captured'})
    body = status(env, qr['collection_id']).json
    assert body['status'] == 'paid' and body['cafe_settlement_status'] == 'pending'
    assert rows(env, 'SELECT settlement_status FROM transactions')[0]['settlement_status'] == 'completed'


def test_payment_after_manual_settlement_flagged_for_review(env):
    tid = add_tx(env, amount=80, kind='extra')
    create(env, booking_types=['extra'])
    with env.app.app_context():
        env.db.session.execute(text("UPDATE transactions SET settlement_status='completed', mode_of_payment='cash' WHERE id=:i"), {'i': tid})
        env.db.session.commit()
    webhook(env, 'qr_1', 8000)
    col = rows(env, 'SELECT status,cafe_settlement_status FROM desk_upi_collections')[0]
    assert col == {'status': 'paid_unapplied', 'cafe_settlement_status': 'review'}
    assert rows(env, 'SELECT mode_of_payment FROM transactions')[0]['mode_of_payment'] == 'cash'


def test_cancel_closes_qr(env):
    add_tx(env, amount=80, kind='extra')
    qr = create(env, booking_types=['extra']).json
    res = env.client.post(f"/api/vendor/1/upi-qr/{qr['collection_id']}/cancel", headers={'X-Test-Vendor': '1'})
    assert res.json['status'] == 'closed' and env.fake.closed == ['qr_1']
    assert status(env, qr['collection_id'], vendor=2).status_code in (403, 404)


def test_multi_slot_booking_collects_one_qr(env):
    add_tx(env, booking=100, amount=200, kind='booking')
    add_tx(env, booking=101, amount=200, kind='booking')
    res = create(env, booking=100, booking_ids=[100, 101])
    assert res.status_code == 201 and res.json['amount_paise'] == 40000
    assert create(env, booking=100, booking_ids=[100, 200]).status_code == 404
    webhook(env, 'qr_1', 40000)
    assert {r['settlement_status'] for r in rows(env, 'SELECT settlement_status FROM transactions')} == {'completed'}
