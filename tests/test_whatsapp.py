"""Isolated PostgreSQL integration tests; no external messages or payments."""
import os
import sys
import json
import uuid
import types
import importlib
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace
import pytest
from flask import Flask,g,jsonify,request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def wa(monkeypatch):
    uri=os.getenv('DESK_TEST_URI')
    if not uri:pytest.skip('DESK_TEST_URI required')
    schema='wa_test_'+uuid.uuid4().hex
    app=Flask(__name__);app.config.update(SQLALCHEMY_DATABASE_URI=uri,SQLALCHEMY_ENGINE_OPTIONS={'connect_args':{'options':f'-csearch_path={schema}'}},RAZORPAY_KEY_ID='test',RAZORPAY_KEY_SECRET='test_secret')
    db=SQLAlchemy(app)
    monkeypatch.setenv('WHATSAPP_CONFIG_KEY',Fernet.generate_key().decode());monkeypatch.setenv('SUPER_ADMIN_API_KEY','admin-test-key')
    services=types.ModuleType('services');services.__path__=[str(ROOT/'services')];monkeypatch.setitem(sys.modules,'services',services)
    controllers=types.ModuleType('controllers');controllers.__path__=[str(ROOT/'controllers')];monkeypatch.setitem(sys.modules,'controllers',controllers)
    ext=types.ModuleType('db.extensions');ext.db=db;monkeypatch.setitem(sys.modules,'db.extensions',ext)
    from functools import wraps
    def permission(*args):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                if request.headers.get('X-Test-Vendor')!=str(kwargs['vendor_id']):return jsonify(error='denied'),403
                g.vendor_claims={};return fn(*args,**kwargs)
            return wrapped
        return decorate
    access=types.ModuleType('services.vendor_access');access.require_vendor_permission=permission;monkeypatch.setitem(sys.modules,access.__name__,access)
    for name in ('services.whatsapp','services.whatsapp_billing','services.whatsapp_automation','controllers.whatsapp_controller','controllers.whatsapp_payments','controllers.whatsapp_preferences','controllers.whatsapp_operations'):
        monkeypatch.delitem(sys.modules,name,raising=False)
    module=importlib.import_module('controllers.whatsapp_controller');module.register_whatsapp(app)
    payments=importlib.import_module('controllers.whatsapp_payments');app.register_blueprint(payments.whatsapp_payments,url_prefix='/api')
    prefs=importlib.import_module('controllers.whatsapp_preferences');app.register_blueprint(prefs.whatsapp_preferences,url_prefix='/api')
    operations=importlib.import_module('controllers.whatsapp_operations');app.register_blueprint(operations.operations,url_prefix='/api')
    service=importlib.import_module('services.whatsapp');billing=importlib.import_module('services.whatsapp_billing')
    with app.app_context():
        db.session.execute(text(f'CREATE SCHEMA {schema}'));db.session.execute(text('CREATE TABLE vendors(id integer primary key,cafe_name text); INSERT INTO vendors VALUES(1,\'Cafe One\'),(2,\'Cafe Two\')'));db.session.commit()
        db.session.execute(text((ROOT/'sql/20261116_whatsapp.sql').read_text()));db.session.commit()
        billing.save_config(dict(ENABLED='true',PHONE_NUMBER_ID='123',API_VERSION='v27.0',ACCESS_TOKEN='secret-token',APP_SECRET='app-secret',VERIFY_TOKEN='verify-secret',PAYMENT_WEBHOOK_SECRET='pay-secret',PACK_PRICE_PAISE='10000',TEMPLATES=json.dumps([{'name':'hfg_update','language':'en','fields':['customer']}])) )
        client=app.test_client();headers={'X-Test-Vendor':'1'}
        client.put('/api/vendor/1/whatsapp/preferences',json={'updates':True},headers=headers)
        yield SimpleNamespace(db=db,client=client,service=service,billing=billing,payments=payments,headers=headers)
        db.session.rollback();db.session.execute(text(f'DROP SCHEMA {schema} CASCADE'));db.session.commit();db.session.remove();db.engine.dispose()


def message(key=None):
    return dict(idempotency_key=key or str(uuid.uuid4()),recipient='+919876543210',template='hfg_update',language='en',parameters=['Alex'],consent=True,consent_note='Customer opted in at desk on 16 Nov',purpose='updates')


def fund(wa,n=100):
    wa.billing.credit(1,n,'test:fund');wa.db.session.commit()


def balance(wa):
    return wa.db.session.execute(text('SELECT credits FROM whatsapp_wallet WHERE vendor_id=1')).scalar() or 0


def test_config_encrypted_and_admin_only(wa):
    assert wa.client.get('/api/admin/whatsapp/config').status_code==401
    result=wa.client.get('/api/admin/whatsapp/config',headers={'x-admin-key':'admin-test-key'})
    assert result.status_code==200 and 'secret-token' not in result.text
    assert 'secret-token' not in wa.db.session.execute(text('SELECT values_encrypted FROM whatsapp_config')).scalar()
    assert wa.client.get('/api/vendor/2/whatsapp',headers=wa.headers).status_code==403


def test_no_credit_no_send_and_idempotent_debit(wa):
    body=message()
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers).status_code==402
    fund(wa,1)
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers).status_code==202
    assert balance(wa)==0
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers).status_code==200
    assert balance(wa)==0
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers).status_code==402


def test_failure_refunds_once_and_unknown_does_not_retry(wa,monkeypatch):
    fund(wa)
    wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers)
    monkeypatch.setattr(wa.service.requests,'post',lambda *a,**kw:SimpleNamespace(ok=False,status_code=400))
    assert wa.service.process_one();assert balance(wa)==100
    assert not wa.service.process_one()
    wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers)
    def timeout(*a,**kw):raise wa.service.requests.Timeout()
    monkeypatch.setattr(wa.service.requests,'post',timeout)
    assert wa.service.process_one();assert balance(wa)==99
    assert not wa.service.process_one()


def webhook(wa,value):
    raw=json.dumps({'entry':[{'changes':[{'value':{'metadata':{'phone_number_id':'123'},**value}}]}]}).encode()
    sig='sha256='+hmac.new(b'app-secret',raw,hashlib.sha256).hexdigest()
    return wa.client.post('/api/whatsapp/webhook',data=raw,content_type='application/json',headers={'X-Hub-Signature-256':sig})


def test_webhook_signature_delivery_order_and_optout(wa,monkeypatch):
    assert wa.client.post('/api/whatsapp/webhook',json={}).status_code==403
    assert wa.client.get('/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verify-secret&hub.challenge=123').text=='123'
    fund(wa);body=message();wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers)
    monkeypatch.setattr(wa.service.requests,'post',lambda *a,**kw:SimpleNamespace(ok=True,json=lambda:{'messages':[{'id':'wamid.1'}]}))
    wa.service.process_one()
    for status in ('read','delivered','sent'):
        assert webhook(wa,{'statuses':[{'id':'wamid.1','status':status}]}).status_code==200
    assert wa.db.session.execute(text('SELECT status FROM whatsapp_outbox')).scalar()=='read'
    webhook(wa,{'messages':[{'from':'919876543210','text':{'body':'STOP'}}]})
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers).status_code==409


def test_payment_requires_capture_amount_vendor_and_only_grants_once(wa):
    purchase=str(uuid.uuid4())
    wa.db.session.execute(text("INSERT INTO whatsapp_purchases(id,vendor_id,amount_paise,order_id) VALUES(:id,1,10000,'order_test')"),{'id':purchase});wa.db.session.commit()
    data=dict(status='authorized',order_id='order_test',currency='INR',amount=10000)
    client=SimpleNamespace(payment=SimpleNamespace(fetch=lambda _:data))
    with pytest.raises(ValueError):wa.billing.grant_purchase(client,'order_test','pay_test',1)
    wa.db.session.rollback();assert balance(wa)==0
    data['status']='captured';data['amount']=1
    with pytest.raises(ValueError):wa.billing.grant_purchase(client,'order_test','pay_test',1)
    wa.db.session.rollback();data['amount']=10000
    with pytest.raises(ValueError):wa.billing.grant_purchase(client,'order_test','pay_test',2)
    wa.db.session.rollback()
    wa.billing.grant_purchase(client,'order_test','pay_test',1)
    wa.billing.grant_purchase(client,'order_test','pay_test',1)
    assert balance(wa)==100


def test_preferences_and_promotion_consent(wa):
    fund(wa)
    assert wa.client.put('/api/vendor/1/whatsapp/preferences',json={'reminders':True,'reminder_minutes':0},headers=wa.headers).status_code==400
    assert wa.client.put('/api/vendor/1/whatsapp/preferences',json={'promotions':True},headers=wa.headers).status_code==200
    body=message();body['purpose']='promotions'
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers).status_code==409
    assert wa.client.put('/api/vendor/1/whatsapp/contacts',json=dict(recipient=body['recipient'],service_consent=False,marketing_consent=True,consent_note='Explicit promotion opt-in today'),headers=wa.headers).status_code==200
    assert wa.client.post('/api/vendor/1/whatsapp/messages',json=body,headers=wa.headers).status_code==202


def test_automation_consent_timing_idempotency_and_booking_link(wa):
    from services.whatsapp_automation import automate_bookings
    fund(wa)
    wa.billing.save_config({'TEMPLATES':json.dumps([
        {'name':'hfg_update','language':'en','fields':['customer']},
        {'name':'hfg_book','language':'en','fields':['cafe','booking_url']}])})
    wa.db.session.execute(text('''
        CREATE TABLE available_games(id integer, vendor_id integer);
        CREATE TABLE users(id integer,name text);
        CREATE TABLE contact_info(parent_id integer,parent_type text,phone text);
        CREATE TABLE slots(id integer,start_time time);
        CREATE TABLE bookings(id integer,game_id integer,user_id integer,slot_id integer,custom_start_time time,status text,created_at timestamptz);
        CREATE TABLE transactions(id integer,booking_id integer,vendor_id integer,booked_date date);
        INSERT INTO available_games VALUES(1,1),(2,2);
        INSERT INTO users VALUES(1,'Alex'),(2,'Unsubscribed');
        INSERT INTO contact_info VALUES(1,'user','9876543210'),(2,'user','9876543211');
        INSERT INTO slots VALUES(1,((now() AT TIME ZONE 'Asia/Kolkata')+interval '30 minutes')::time);
        INSERT INTO bookings VALUES(1,1,1,1,NULL,'confirmed',now()+interval '1 second'),(2,1,2,1,NULL,'confirmed',now()+interval '1 second');
        INSERT INTO transactions VALUES(1,1,1,((now() AT TIME ZONE 'Asia/Kolkata')+interval '30 minutes')::date),(2,2,1,((now() AT TIME ZONE 'Asia/Kolkata')+interval '30 minutes')::date);
    '''));wa.db.session.commit()
    prefs=dict(confirmations=True,reminders=True,confirmation_template='hfg_update:en',reminder_template='hfg_update:en',reminder_minutes=60,booking_link=True,booking_template='hfg_book:en',booking_url='https://hashforgamers.com/cafes/1')
    assert wa.client.put('/api/vendor/1/whatsapp/preferences',json=prefs,headers=wa.headers).status_code==200
    assert wa.client.put('/api/vendor/1/whatsapp/contacts',json=dict(recipient='+919876543210',service_consent=True,marketing_consent=False,consent_note='Service opt-in today'),headers=wa.headers).status_code==200
    automate_bookings();automate_bookings()
    assert balance(wa)==98
    assert wa.db.session.execute(text('SELECT count(*) FROM whatsapp_outbox')).scalar()==2
    msg={'id':'inbound-1','from':'919876543210','text':{'body':'BOOK 1'}}
    assert webhook(wa,{'messages':[msg]}).status_code==200
    assert webhook(wa,{'messages':[msg]}).status_code==200
    assert balance(wa)==97
    # Wrong cafe has no enabled booking handler, and cannot spend cafe 1's wallet.
    msg={'id':'inbound-2','from':'919876543210','text':{'body':'BOOK 2'}}
    assert webhook(wa,{'messages':[msg]}).status_code==200
    assert balance(wa)==97


def test_payment_webhook_replay_and_invalid_signature(wa,monkeypatch):
    pid=str(uuid.uuid4())
    wa.db.session.execute(text("INSERT INTO whatsapp_purchases(id,vendor_id,amount_paise,order_id) VALUES(:id,1,10000,'order_hook')"),{'id':pid});wa.db.session.commit()
    client=SimpleNamespace(payment=SimpleNamespace(fetch=lambda _:dict(status='captured',order_id='order_hook',currency='INR',amount=10000)))
    monkeypatch.setattr(wa.payments,'gateway',lambda:(client,'key'))
    raw=json.dumps({'event':'payment.captured','payload':{'payment':{'entity':{'id':'pay_hook','order_id':'order_hook'}}}}).encode()
    url='/api/whatsapp/payment-webhook'
    assert wa.client.post(url,data=raw,content_type='application/json').status_code==403
    sig=hmac.new(b'pay-secret',raw,hashlib.sha256).hexdigest()
    for _ in range(2):assert wa.client.post(url,data=raw,content_type='application/json',headers={'X-Razorpay-Signature':sig}).status_code==200
    assert balance(wa)==100


def test_disabling_rule_refunds_queued_message(wa,monkeypatch):
    fund(wa)
    wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers)
    assert balance(wa)==99
    wa.client.put('/api/vendor/1/whatsapp/preferences',json={'updates':False},headers=wa.headers)
    def must_not_send(*a,**kw):raise AssertionError('Disabled messages must not reach Meta')
    monkeypatch.setattr(wa.service.requests,'post',must_not_send)
    wa.service.process_one()
    assert balance(wa)==100
    assert wa.db.session.execute(text('SELECT status FROM whatsapp_outbox')).scalar()=='suppressed'


def test_failed_delivery_callback_refunds_only_once(wa,monkeypatch):
    fund(wa)
    wa.client.post('/api/vendor/1/whatsapp/messages',json=message(),headers=wa.headers)
    monkeypatch.setattr(wa.service.requests,'post',lambda *a,**kw:SimpleNamespace(ok=True,json=lambda:{'messages':[{'id':'wamid.fail'}]}))
    wa.service.process_one()
    assert balance(wa)==99
    for _ in range(2):assert webhook(wa,{'statuses':[{'id':'wamid.fail','status':'failed'}]}).status_code==200
    assert balance(wa)==100


def test_operations_report_is_authenticated_and_uses_paid_revenue(wa):
    url='/api/admin/whatsapp/operations'
    assert wa.client.get(url).status_code==401
    fund(wa)
    wa.db.session.execute(text("INSERT INTO whatsapp_purchases(id,vendor_id,amount_paise,status,paid_at) VALUES(:id,1,10000,'paid',now())"),{'id':str(uuid.uuid4())});wa.db.session.commit()
    data=wa.client.get(url,headers={'x-admin-key':'admin-test-key'}).json
    assert data['purchases']=={'packs':1,'revenue_paise':10000}
    assert data['credits']['balance']==100
    assert data['cafes'][0]['cafe_name']=='Cafe One'
    assert wa.client.get(url+'?days=1000',headers={'x-admin-key':'admin-test-key'}).status_code==400


def test_read_only_validation_and_meta_costs(wa,monkeypatch):
    import controllers.whatsapp_operations as operations
    wa.billing.save_config({'WABA_ID':'456'})
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        if url.endswith('/123'):body={'id':'123','verified_name':'Hash for Gamers','display_phone_number':'123','quality_rating':'GREEN'}
        elif url.endswith('/phone_numbers'):body={'data':[{'id':'123'}]}
        elif url.endswith('/message_templates'):body={'data':[{'name':'hfg_update','language':'en','status':'APPROVED'}]}
        elif url.endswith('/pricing_analytics'):body={'data':[{'data_points':[{'start':1,'end':2,'pricing_category':'UTILITY','volume':3,'cost':'1.25'}]}]}
        elif 'razorpay' in url:body={'items':[]}
        else:body={'name':'HFG','currency':'INR'}
        return SimpleNamespace(ok=True,json=lambda:body)
    monkeypatch.setattr(operations.requests,'get',get)
    headers={'x-admin-key':'admin-test-key'}
    response=wa.client.post('/api/admin/whatsapp/validate',headers=headers)
    assert response.status_code==200
    assert all(c['status']=='passed' for c in response.json['checks'][:4])
    assert 'secret-token' not in response.text and 'app-secret' not in response.text
    report=wa.client.get('/api/admin/whatsapp/meta-report',headers=headers).json
    assert report['cost']=='1.25' and report['balance'] is None
    assert report['currency']=='INR'
    monkeypatch.setattr(operations.requests,'get',lambda *a,**kw:SimpleNamespace(ok=False,status_code=401))
    failed=wa.client.get('/api/admin/whatsapp/meta-report',headers=headers)
    assert failed.status_code==502 and 'cost' not in failed.json


def test_webhook_evidence_and_old_api_version(wa):
    headers={'x-admin-key':'admin-test-key'}
    assert wa.client.put('/api/admin/whatsapp/config',headers=headers,json={'API_VERSION':'v1.0'}).status_code==400
    webhook(wa,{'statuses':[]})
    body=wa.client.get('/api/admin/whatsapp/operations',headers=headers).json
    assert body['webhook_checks'][0]['name']=='meta_signed_callback'
    assert body['webhook_checks'][0]['current'] is True
    wa.billing.save_config({'VERIFY_TOKEN':'rotated-token'})
    body=wa.client.get('/api/admin/whatsapp/operations',headers=headers).json
    assert body['webhook_checks'][0]['current'] is False
