"""Run with DESK_TEST_URI pointing at a disposable PostgreSQL database."""
import importlib.util
import os
import sys
import types
import uuid
from pathlib import Path
from datetime import time
import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def env(monkeypatch):
    uri=os.getenv('DESK_TEST_URI')
    if not uri:
        pytest.skip('DESK_TEST_URI is required for isolated PostgreSQL integration tests')
    schema='desk_test_'+uuid.uuid4().hex
    app=Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri,SQLALCHEMY_ENGINE_OPTIONS={'connect_args':{'options':f'-csearch_path={schema}'}})
    db=SQLAlchemy(app)
    services=types.ModuleType('services');services.__path__=[str(ROOT/'services')];monkeypatch.setitem(sys.modules,'services',services)
    ext=types.ModuleType('db.extensions');ext.db=db;monkeypatch.setitem(sys.modules,'db.extensions',ext)
    access=types.ModuleType('services.vendor_access');access.require_vendor_permission=lambda *args:lambda f:f;monkeypatch.setitem(sys.modules,access.__name__,access)
    spec=importlib.util.spec_from_file_location('tested_desk_operations',ROOT/'controllers/desk_operations.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);app.register_blueprint(module.desk,url_prefix='/api')
    with app.app_context():
        db.session.execute(text(f'CREATE SCHEMA {schema}'))
        db.session.execute(text('CREATE TABLE vendors(id integer primary key); CREATE TABLE available_games(id integer primary key,vendor_id integer); CREATE TABLE cafe_passes(id integer); INSERT INTO vendors VALUES(1),(2); INSERT INTO available_games VALUES(1,1),(2,2)'))
        db.session.commit()
        for filename in ['20261103_desk_rates_and_history.sql','20261108_unified_pricing.sql','20261109_custom_desk_pricing.sql','20261109_custom_desk_pricing.sql']:
            db.session.execute(text((ROOT/'sql'/filename).read_text()));db.session.commit()
        db.session.execute(text("""CREATE TABLE consoles(id integer primary key,vendor_id integer,model_number text);
          CREATE TABLE available_game_console(available_game_id integer,console_id integer);
          CREATE TABLE hardware_specifications(console_id integer,screen_size_inches integer);
          CREATE TABLE maintenance_status(console_id integer,available_status text);
          CREATE TABLE bookings(id integer primary key,squad_details jsonb);
          CREATE TABLE vendor_1_dashboard(book_id integer,console_id integer,book_status text,date date,start_time time,end_time time);
          CREATE TABLE cafe_play_sessions(console_claim integer,ends_at timestamp,booking_end timestamp,deadline timestamp,minutes integer,started_at timestamp,created_at timestamp);
          INSERT INTO consoles VALUES(11,1,'PS 55'),(12,1,'PS 77'),(13,2,'Other cafe'),(14,1,'PS 77 B');
          INSERT INTO available_game_console VALUES(1,11),(1,12),(2,13),(1,14);
          INSERT INTO hardware_specifications VALUES(11,55),(12,77),(13,77),(14,77);
        """));db.session.commit()
        db.session.execute(text((ROOT/'sql/20261110_desk_console_assignment.sql').read_text()));db.session.commit()
        yield types.SimpleNamespace(client=app.test_client(),db=db,module=module)
        db.session.rollback();db.session.execute(text(f'DROP SCHEMA {schema} CASCADE'));db.session.commit();db.session.remove();db.engine.dispose()

def card():
    return dict(game_id=1,profile='custom_example',definition=dict(name='Premium',model_name='Weekend group',screen_size_inches=77,game_variant='Custom game',controllers_included=True,rules=[dict(min_minutes=1,max_minutes=None,min_players=1,max_players=8,amount='99.50',unit_minutes=45,per_player=True)]))

def test_custom_pricing_lifecycle_and_scope(env):
    e=env;url='/api/vendor/1/desk-rates'
    data=card();assert e.client.put(url,json=data).status_code==200
    saved=e.client.get(url).json[0]
    assert saved['definition']['screen_size_inches']==77 and saved['pricing_mode']=='variants'
    slots=[types.SimpleNamespace(id=1,start_time=time(10),end_time=time(10,30)),types.SimpleNamespace(id=2,start_time=time(10,30),end_time=time(11,30))]
    assert sum(e.module.desk_slot_prices(1,1,data['profile'],6,slots,revision=1).values())==1194
    assert e.client.put('/api/vendor/2/desk-rates',json=data).status_code==400
    assert e.client.get('/api/vendor/2/desk-rates').json==[]
    data['revision']=1;data['definition']['rules'][0]['amount']='100'
    assert e.client.put(url,json=data).status_code==200
    assert e.client.put(url,json=data).status_code==409
    with pytest.raises(ValueError):e.module.desk_slot_prices(1,1,data['profile'],6,slots,revision=1)
    assert e.client.patch(url,json=dict(game_id=1,profile=data['profile'],revision=2,archived=True)).status_code==200
    with pytest.raises(ValueError):e.module.desk_slot_prices(1,1,data['profile'],6,slots)
    assert e.client.patch(url,json=dict(game_id=1,profile=data['profile'],revision=3,archived=False)).status_code==200
    restored=e.client.get(url).json[0];assert not restored['archived'] and not restored['is_active']
    assert e.client.patch(url,json=dict(game_id=1,profile=data['profile'],revision=4,is_active=True)).status_code==200
    assert sum(e.module.desk_slot_prices(1,1,data['profile'],6,slots,revision=5).values())==1200
    assert e.client.put(url+'/mode',json=dict(game_id=1,mode='slot')).status_code==200
    saved=e.client.get(url).json[0];assert saved['is_active'] and saved['pricing_mode']=='slot'
    with pytest.raises(ValueError):e.module.desk_slot_prices(1,1,data['profile'],6,slots)
    assert e.client.put(url+'/mode',json=dict(game_id=1,mode='variants')).status_code==200
    assert sum(e.module.desk_slot_prices(1,1,data['profile'],6,slots).values())==1200


def test_ambiguous_rules_never_persist(env):
    data=card();data['definition']['rules']*=2
    result=env.client.put('/api/vendor/1/desk-rates',json=data)
    assert result.status_code==400 and 'overlap' in result.json['error']
    assert env.client.get('/api/vendor/1/desk-rates').json==[]


def test_console_mapping_scope_screen_and_reservation(env):
    from services.desk_consoles import reserve, windows
    from datetime import date
    data=card();data['definition']['console_ids']=[11]
    assert env.client.put('/api/vendor/1/desk-rates',json=data).status_code==400
    data['definition']['console_ids']=[13]
    assert env.client.put('/api/vendor/1/desk-rates',json=data).status_code==400
    data['definition']['console_ids']=[12,14]
    assert env.client.put('/api/vendor/1/desk-rates',json=data).status_code==200
    spans=windows(date(2030,1,1),[types.SimpleNamespace(start_time=time(23),end_time=time(1))])
    assert reserve(1,1,data['definition'],spans,1,[12])==[12]
    env.db.session.execute(text("INSERT INTO bookings VALUES(1,'{\"desk_console_ids\":[12],\"assigned_console_ids\":[12]}'); INSERT INTO vendor_1_dashboard VALUES(1,12,'upcoming','2030-01-01','23:00','01:00')"));env.db.session.commit()
    with pytest.raises(ValueError):reserve(1,1,data['definition'],spans,1,[12])
    assert reserve(1,1,data['definition'],spans,1)==[14]
    env.db.session.execute(text("UPDATE vendor_1_dashboard SET book_status='cancelled' WHERE book_id=1"));env.db.session.commit()
    assert reserve(1,1,data['definition'],spans,1,[12])==[12]
    env.db.session.rollback()


def test_assignment_guard_blocks_wrong_console_and_other_bookings(env):
    from sqlalchemy.exc import IntegrityError
    env.db.session.execute(text("INSERT INTO bookings VALUES(1,'{\"desk_console_ids\":[12]}'),(2,'{}'); INSERT INTO vendor_1_dashboard VALUES(1,12,'upcoming','2030-01-01','10:00','11:00')"));env.db.session.commit()
    with pytest.raises(IntegrityError):
        env.db.session.execute(text("UPDATE vendor_1_dashboard SET console_id=11,book_status='current' WHERE book_id=1"))
    env.db.session.rollback()
    with pytest.raises(IntegrityError):
        env.db.session.execute(text("INSERT INTO vendor_1_dashboard VALUES(2,12,'current','2030-01-01','10:30','11:30')"))
    env.db.session.rollback()
    env.db.session.execute(text("UPDATE vendor_1_dashboard SET book_status='current' WHERE book_id=1"));env.db.session.commit()
