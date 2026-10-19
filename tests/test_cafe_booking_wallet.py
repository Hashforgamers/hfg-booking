import ast,os,uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine,text,event
from sqlalchemy.orm import scoped_session,sessionmaker
from concurrent.futures import ThreadPoolExecutor

@pytest.fixture
def wallet():
    url=os.getenv('CAFE_TEST_DATABASE_URL')
    if not url:pytest.skip('Disposable PostgreSQL required')
    engine=create_engine(url);schema='scheduled_'+uuid.uuid4().hex
    with engine.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    def checkout(conn,*a):
        with conn.cursor() as c:c.execute(f'SET search_path TO {schema}')
        conn.commit()
    event.listen(engine,'checkout',checkout)
    with engine.begin() as c:
        c.execute(text('CREATE TABLE cafe_wallets(vendor_id integer,user_id integer,balance bigint,reserved bigint,PRIMARY KEY(vendor_id,user_id)); INSERT INTO cafe_wallets VALUES(1,77,10000,2000),(2,77,50000,0)'))
        c.execute(text('''CREATE TABLE cafe_wallet_ledger(id serial PRIMARY KEY,vendor_id integer,user_id integer,kind text,amount bigint,balance_after bigint,reserved_after bigint,actor_id text,actor_name text,method text,reason text,idempotency_key text,fingerprint text,created_at timestamp,UNIQUE(vendor_id,idempotency_key))'''))
    sessions=scoped_session(sessionmaker(bind=engine));scope={'db':SimpleNamespace(session=sessions)}
    tree=ast.parse((Path(__file__).parents[1]/'services/cafe_booking_wallet.py').read_text());tree.body=[n for n in tree.body if not isinstance(n,ast.ImportFrom) or n.module!='db.extensions'];exec(compile(tree,'wallet','exec'),scope)
    yield scope['move'],sessions
    sessions.remove();event.remove(engine,'checkout',checkout)
    with engine.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()

def test_debit_replay_refund_and_cafe_isolation(wallet):
    move,s=wallet
    assert move(1,77,5,30)==3000;s.commit()
    assert move(1,77,5,30)==3000;s.commit()
    move(1,77,5,10,component='controller');s.commit()
    move(1,77,5,35,refund=True);s.commit()
    move(1,77,5,35,refund=True);s.commit()
    assert s.execute(text('SELECT balance FROM cafe_wallets WHERE vendor_id=1')).scalar()==9500
    assert s.execute(text('SELECT balance FROM cafe_wallets WHERE vendor_id=2')).scalar()==50000
    assert s.execute(text('SELECT COUNT(*) FROM cafe_wallet_ledger')).scalar()==3

def test_concurrent_no_overdraw_and_reserved_funds(wallet):
    move,s=wallet
    def buy(bid):
        try:move(1,77,bid,50);s.commit();return True
        except ValueError:s.rollback();return False
        finally:s.remove()
    with ThreadPoolExecutor(max_workers=3) as pool:assert sorted(pool.map(buy,[1,2,3]))==[False,False,True]
    assert s.execute(text('SELECT balance FROM cafe_wallets WHERE vendor_id=1')).scalar()==5000

def test_rollback_and_refund_bounds(wallet):
    move,s=wallet
    move(1,77,5,30);s.rollback()
    assert s.execute(text('SELECT COUNT(*) FROM cafe_wallet_ledger')).scalar()==0
    with pytest.raises(ValueError):move(1,77,5,30,refund=True)
    s.rollback()
    move(1,77,5,30);s.commit()
    with pytest.raises(ValueError):move(1,77,5,31,refund=True)
    s.rollback()
