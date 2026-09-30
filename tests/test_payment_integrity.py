"""Payment invariants against real ORM code in isolated PostgreSQL schemas.

External gateway responses are mocked; no live money or production DB is used.
"""
import ast
import importlib.util
import os
import sys
import types
import uuid
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta, time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def env(monkeypatch):
    app=Flask(__name__)
    url=os.getenv('PAYMENT_TEST_DATABASE_URL','sqlite://')
    schema='payment_test_'+uuid.uuid4().hex
    app.config.update(SQLALCHEMY_DATABASE_URI=url, JWT_SECRET_KEY='secret'*10)
    if url.startswith('postgresql'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS']={'connect_args':{'options':f'-csearch_path={schema}'}}
    db=SQLAlchemy(app)
    for name in ['db','models','services']:
        mod=types.ModuleType(name);mod.__path__=[];monkeypatch.setitem(sys.modules,name,mod)
    ext=types.ModuleType('db.extensions');ext.db=db;monkeypatch.setitem(sys.modules,ext.__name__,ext)
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules,name,m);spec.loader.exec_module(m);return m
    def expose(name,cls):
        mod=types.ModuleType(name);setattr(mod,cls.__name__,cls);monkeypatch.setitem(sys.modules,name,mod)
    class User(db.Model):
        __tablename__='users'
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String,default='Gamer')
    class Vendor(db.Model):
        __tablename__='vendors'
        id=db.Column(db.Integer,primary_key=True)
        transactions=db.relationship('Transaction',back_populates='vendor')
    class AvailableGame(db.Model):
        __tablename__='available_games'
        id=db.Column(db.Integer,primary_key=True)
        vendor_id=db.Column(db.Integer)
    class Booking(db.Model):
        __tablename__='bookings'
        id=db.Column(db.Integer,primary_key=True)
        user_id=db.Column(db.Integer)
        game_id=db.Column(db.Integer)
        transaction=db.relationship('Transaction',back_populates='booking')
    class Slot(db.Model):
        __tablename__='slots'
        id=db.Column(db.Integer,primary_key=True)
        start_time=db.Column(db.Time)
        end_time=db.Column(db.Time)
    for name,cls in [('user',User),('vendor',Vendor),('booking',Booking),('slot',Slot),('availableGame',AvailableGame)]:expose('models.'+name,cls)
    passes=load('models.passModels','models/passModels.py')
    tx=load('models.transaction','models/transaction.py')
    wallet=load('models.hashWallet','models/hashWallet.py')
    ledger=load('models.hashWalletTransaction','models/hashWalletTransaction.py')
    receipt=load('models.passPurchase','models/passPurchase.py')
    gateway=load('models.bookingGatewayPayment','models/bookingGatewayPayment.py')
    methods=load('services.payment_methods','services/payment_methods.py')
    ps=load('services.pass_service','services/pass_service.py')
    otp=load('services.pass_otp_store','services/pass_otp_store.py')
    # Load the production debit function without unrelated booking/network imports.
    tree=ast.parse((ROOT/'services/booking_service.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BookingService')
    debit=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='debit_wallet')
    module=types.ModuleType('services.booking_service')
    module.__dict__.update(db=db,Decimal=Decimal,InvalidOperation=InvalidOperation,HashWallet=wallet.HashWallet,HashWalletTransaction=ledger.HashWalletTransaction)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='BookingService',bases=[],keywords=[],body=[debit],decorator_list=[])],type_ignores=[])),str(ROOT/'services/booking_service.py'),'exec'),module.__dict__)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    purchase=load('services.pass_purchase_service','services/pass_purchase_service.py')
    fake=Mock()
    fake.payment.fetch.return_value={'order_id':'order_1','status':'captured','currency':'INR','amount':10000}
    fake.order.fetch.return_value={'notes':{'user_id':'1','cafe_pass_id':'1'}}
    monkeypatch.setattr(purchase.razorpay,'Client',lambda **kw:fake)
    with app.app_context():
        if url.startswith('postgresql'):
            with db.engine.begin() as conn:conn.execute(text(f'CREATE SCHEMA {schema}'))
        db.create_all()
        db.session.execute(text('CREATE TABLE payment_method(pay_method_id integer PRIMARY KEY,method_name varchar UNIQUE)'))
        db.session.execute(text('CREATE TABLE payment_vendor_map(vendor_id integer,pay_method_id integer)'))
        db.session.execute(text("INSERT INTO payment_method VALUES(1,'hash_global_pass'),(2,'cafe_specific_pass'),(3,'hash_wallet'),(4,'payment_gateway')"))
        db.session.execute(text('INSERT INTO payment_vendor_map VALUES(1,1),(1,2),(1,3),(1,4),(2,1),(2,2)'))
        db.session.add_all([User(id=1),User(id=2),Vendor(id=1),Vendor(id=2),AvailableGame(id=1,vendor_id=1),AvailableGame(id=2,vendor_id=2),Slot(id=1,start_time=time(23,30),end_time=time(1)),Booking(id=1,user_id=1,game_id=1),Booking(id=2,user_id=2,game_id=1),Booking(id=3,user_id=1,game_id=2)])
        db.session.flush()
        db.session.add(passes.CafePass(id=1,vendor_id=1,name='10 hours',price=100,days_valid=30,pass_mode='hour_based',total_hours=10,hour_calculation_mode='actual_duration'))
        db.session.add(wallet.HashWallet(user_id=1,balance=200))
        db.session.commit()
    e=types.SimpleNamespace(app=app,db=db,p=passes,ps=ps.PassService,b=module.BookingService,w=wallet.HashWallet,l=ledger.HashWalletTransaction,g=gateway.BookingGatewayPayment,tx=tx.Transaction,buy=purchase.purchase,fake=fake,otp=otp,methods=methods,pg=url.startswith('postgresql'))
    yield e
    with app.app_context():
        db.session.remove()
        if e.pg:
            with db.engine.begin() as conn:conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        db.engine.dispose()


def body(**kw):return dict(cafe_pass_id=1,payment_mode='wallet',idempotency_key='purchase-001',**kw)

def test_wallet_purchase_retry_and_conflicting_key(env):
    e=env
    with e.app.app_context():
        owned,tx,replay=e.buy(1,body());e.db.session.commit()
        same,tx2,replay=e.buy(1,body());e.db.session.commit()
        assert same.id==owned.id and tx==tx2 and replay
        assert e.w.query.one().balance==100 and e.l.query.count()==1 and e.tx.query.count()==1
        with pytest.raises(ValueError,match='Idempotency'):e.buy(1,dict(body(),cafe_pass_id=2))

@pytest.mark.parametrize('changes',[{'status':'authorized'},{'amount':1},{'currency':'USD'}])
def test_gateway_requires_exact_captured_inr_payment(env,changes):
    e=env
    with e.app.app_context():
        e.fake.payment.fetch.return_value.update(changes)
        with pytest.raises(ValueError,match='Captured'):e.buy(1,dict(body(),payment_mode='gateway',payment_id='pay_1'))
        e.db.session.rollback()
        assert e.p.UserPass.query.count()==0 and e.g.query.count()==0


def test_gateway_owner_pass_binding_and_cross_checkout_replay(env):
    e=env
    with e.app.app_context():
        e.fake.order.fetch.return_value['notes']['user_id']='2'
        with pytest.raises(ValueError,match='belong'):e.buy(1,dict(body(),payment_mode='gateway',payment_id='pay_1'))
        e.db.session.rollback()
        e.fake.order.fetch.return_value['notes']['user_id']='1'
        e.db.session.add(e.g(payment_id='pay_1',order_id='order_1',user_id=1,amount=100,status='completed'));e.db.session.commit()
        with pytest.raises(ValueError,match='already used'):e.buy(1,dict(body(),payment_mode='gateway',payment_id='pay_1'))
        e.db.session.rollback()
        assert e.p.UserPass.query.count()==0


def test_gateway_success_and_replay(env):
    e=env
    with e.app.app_context():
        request=dict(body(),payment_mode='gateway',payment_id='pay_1')
        first=e.buy(1,request)[0].id;e.db.session.commit()
        assert e.buy(1,request)[0].id==first;e.db.session.commit()
        assert e.g.query.count()==1 and e.w.query.one().balance==200


def test_failed_booking_rolls_back_pass_and_verification_consumption(env):
    e=env
    with e.app.app_context():
        owned=e.buy(1,body())[0];e.db.session.commit();pid=owned.id
        store=e.otp.PassOtpStore('verified');store['secret']={'expires_at':9999999999,'user_id':1};e.db.session.commit()
        store.pop('secret')
        e.ps.redeem_pass_hours(pid,1,Decimal('1.5'),'app_booking',booking_id=1)
        e.db.session.rollback()
        assert store.get('secret') and e.db.session.get(e.p.UserPass,pid).remaining_hours==10
        assert e.p.PassRedemptionLog.query.count()==0


def test_pass_owner_vendor_disabled_method_and_booking_checks(env):
    e=env
    with e.app.app_context():
        owned=e.buy(1,body())[0];e.db.session.commit();pid=owned.id;uid=owned.pass_uid
        assert e.ps.get_valid_user_pass(user_id=2,vendor_id=1,pass_uid=uid) is None
        assert e.ps.get_valid_user_pass(user_id=1,vendor_id=2,pass_uid=uid) is None
        for booking,vid in [(2,1),(3,1),(1,2)]:
            with pytest.raises(ValueError):e.ps.redeem_pass_hours(pid,vid,1,'app_booking',booking_id=booking)
            e.db.session.rollback()
        e.db.session.execute(text('DELETE FROM payment_vendor_map WHERE vendor_id=1 AND pay_method_id=2'));e.db.session.commit()
        with pytest.raises(ValueError,match='disabled'):e.ps.redeem_pass_hours(pid,1,1,'app_booking',booking_id=1)
        e.db.session.rollback()
        assert e.db.session.get(e.p.UserPass,pid).remaining_hours==10


def test_hours_actual_duration_idempotency_and_restore(env):
    e=env
    with e.app.app_context():
        owned=e.buy(1,body())[0];e.db.session.commit();pid=owned.id
        assert e.ps.calculate_slot_hours(1,owned.cafe_pass)==Decimal('1.50')
        redemption=e.ps.redeem_pass_hours(pid,1,Decimal('1.50'),'app_booking',booking_id=1);e.db.session.commit();rid=redemption.id
        assert e.ps.redeem_pass_hours(pid,1,Decimal('1.50'),'app_booking',booking_id=1).id==rid
        assert e.db.session.get(e.p.UserPass,pid).remaining_hours==Decimal('8.50')
        e.ps.cancel_redemption(rid);e.db.session.commit()
        e.ps.cancel_redemption(rid);e.db.session.commit()
        assert e.db.session.get(e.p.UserPass,pid).remaining_hours==10

@pytest.mark.parametrize('amount',['NaN','Infinity','-1','0','1.005'])
def test_invalid_wallet_amount_cannot_move_money(env,amount):
    e=env
    with e.app.app_context():
        with pytest.raises(ValueError):e.b.debit_wallet(1,1,amount)
        assert e.w.query.one().balance==200 and e.l.query.count()==0


def test_concurrent_wallet_purchase_only_debits_once(env):
    e=env
    if not e.pg:pytest.skip('PostgreSQL row locks required')
    def run():
        with e.app.app_context():
            result=e.buy(1,body());pid=result[0].id;e.db.session.commit();return pid
    with ThreadPoolExecutor(max_workers=2) as pool: ids=list(pool.map(lambda _:run(),range(2)))
    with e.app.app_context():
        assert ids[0]==ids[1] and e.w.query.one().balance==100 and e.l.query.count()==1


def test_vendor_guard_rejects_gamer_cross_cafe_and_wrong_internal_action(env,monkeypatch):
    import jwt
    import time as clock
    from flask import jsonify
    e=env
    spec=importlib.util.spec_from_file_location('services.vendor_access',ROOT/'services/vendor_access.py')
    access=importlib.util.module_from_spec(spec);spec.loader.exec_module(access)
    @access.require_vendor_permission('booking.manage')
    def financial_action():return jsonify(ok=True)
    e.app.add_url_rule('/desk','financial_action',financial_action,methods=['POST'])
    c=e.app.test_client();now=int(clock.time())
    def headers(subject,**claims):
        return {'Authorization':'Bearer '+jwt.encode(dict(sub=subject,iat=now,exp=now+60,**claims),e.app.config['JWT_SECRET_KEY'],algorithm='HS256')}
    assert c.post('/desk',json={'vendor_id':1}).status_code==401
    assert c.post('/desk',json={'vendor_id':1},headers=headers({'id':1,'type':'user'})).status_code==403
    owner=headers({'id':1,'type':'vendor'})
    assert c.post('/desk',json={'vendor_id':1},headers=owner).status_code==200
    assert c.post('/desk',json={'vendor_id':2},headers=owner).status_code==403
    assert c.post('/desk',json={'vendor_id':1,'booking_id':3},headers=owner).status_code==403
    with e.app.app_context():scoped=access.internal_booking_headers(1,1,'accept')
    assert c.post('/desk',json={'vendor_id':1,'booking_id':1},headers=scoped).status_code==403


def test_disabled_cafe_pass_purchase_does_not_debit(env):
    e=env
    with e.app.app_context():
        e.db.session.execute(text('DELETE FROM payment_vendor_map WHERE vendor_id=1 AND pay_method_id=2'));e.db.session.commit()
        with pytest.raises(ValueError,match='disabled'):e.buy(1,body())
        e.db.session.rollback()
        assert e.w.query.one().balance==200 and e.p.UserPass.query.count()==0


def test_otp_attempt_updates_and_single_consumer_are_durable(env):
    e=env
    with e.app.app_context():
        store=e.otp.PassOtpStore('otp')
        store['challenge']={'attempts_remaining':5,'expires_at':9999999999}
        e.db.session.commit()
        store.get('challenge')['attempts_remaining']=4;e.db.session.commit();e.db.session.remove()
        assert store.get('challenge')['attempts_remaining']==4
        store.pop('challenge');e.db.session.commit();e.db.session.remove()
        assert store.get('challenge') is None

@pytest.mark.parametrize('amount',['NaN','Infinity','-1','0','1.005'])
def test_invalid_pass_hours_do_not_change_balance(env,amount):
    e=env
    with e.app.app_context():
        owned=e.buy(1,body())[0];e.db.session.commit();pid=owned.id
        with pytest.raises(ValueError):e.ps.redeem_pass_hours(pid,1,amount,'app_booking',booking_id=1)
        e.db.session.rollback()
        assert e.db.session.get(e.p.UserPass,pid).remaining_hours==10
