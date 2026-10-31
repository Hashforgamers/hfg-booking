"""Saved hours must win over spare capacity in booking readers and preflight."""
import ast
from datetime import time as clock_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading

ROOT = Path(__file__).resolve().parents[1]


def compile_functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope


def test_single_slot_listing_does_not_offer_disabled_capacity():
    query = Mock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(total_slot=3, single_slot_price=100)
    scope = dict(time=SimpleNamespace(time=lambda: 1), _slots_single_cache_lock=threading.Lock(),
        _slots_single_cache={}, _force_slot_refresh=lambda: True,
        AvailableGame=SimpleNamespace(query=query), SLOTS_SINGLE_CACHE_TTL_SEC=0,
        jsonify=lambda data: SimpleNamespace(json=data, headers={}),
        _load_vendor_slot_rows=lambda *args: [(1,False,3,clock_time(9),clock_time(10)),
                                              (2,True,2,clock_time(10),clock_time(11))],
        _load_booking_counts=lambda *args: {}, _expected_blocks_for_date=lambda *args: None)
    compile_functions('controllers/slot_controller.py', {'get_slots_on_game_id','_prefer_slot_candidate'}, scope)
    response, status = scope['get_slots_on_game_id'](1,2,'20261102')
    assert status == 200, response.json
    assert response.json['slots'][0]['is_available'] is False
    assert response.json['slots'][0]['available_slot'] == 0
    assert response.json['slots'][1]['available_slot'] == 2


def test_precheck_rejects_disabled_slot_with_positive_capacity():
    session = Mock()
    session.execute.return_value.fetchone.return_value = (3,False)
    scope = compile_functions('controllers/booking_controller.py', {'_precheck_slot_booking_eligibility'},
        dict(db=SimpleNamespace(session=session), text=lambda sql:sql))
    assert scope['_precheck_slot_booking_eligibility'](1,2,'2026-11-02',1) == 'Slot is marked unavailable.'


def test_closed_day_is_distinct_from_missing_legacy_configuration():
    from datetime import datetime
    from sqlalchemy import text
    for opening, expected in [([(False,)], set()), ([], None)]:
        session=Mock()
        session.execute.return_value.fetchall.side_effect=[opening, []]
        scope=compile_functions('controllers/slot_controller.py', {'_expected_blocks_for_date'},
            dict(db=SimpleNamespace(session=session), text=text, datetime=datetime,
                 time=SimpleNamespace(time=lambda:1), _expected_blocks_cache_lock=threading.Lock(),
                 _expected_blocks_cache={}))
        assert scope['_expected_blocks_for_date'](1,'2026-11-02') == expected


def test_direct_booking_does_not_recreate_closed_day_slots(monkeypatch):
    import sys
    from datetime import date
    module=SimpleNamespace(_expected_blocks_for_date=lambda *args:set())
    monkeypatch.setitem(sys.modules,'controllers.slot_controller',module)
    game_query=Mock()
    game_query.filter_by.return_value.first.return_value=SimpleNamespace(total_slot=3)
    slot_query=Mock()
    slot_query.filter.return_value.all.return_value=[SimpleNamespace(id=7,start_time=clock_time(9),end_time=clock_time(10))]
    session=Mock()
    session.query.return_value.filter.return_value.all.return_value=[(7,)]
    scope=compile_functions('controllers/booking_controller.py', {'_ensure_vendor_slot_rows_for_date'},
        dict(db=SimpleNamespace(session=session), AvailableGame=SimpleNamespace(query=game_query),
             Slot=SimpleNamespace(query=slot_query,id=Mock(),gaming_type_id=Mock())))
    scope['_ensure_vendor_slot_rows_for_date'](1,2,date(2026,11,2),[7])
    session.execute.assert_not_called()


def test_batch_listing_does_not_offer_disabled_capacity():
    from datetime import date
    from sqlalchemy import text, bindparam
    session=Mock()
    session.execute.return_value.fetchall.return_value=[(1,date(2026,11,2),False,3,clock_time(9),clock_time(10),2,100,2)]
    game_query=Mock()
    game_query.filter.return_value.all.return_value=[SimpleNamespace(id=2,total_slot=3)]
    scope=compile_functions('controllers/slot_controller.py', {'get_slots_batch','_prefer_slot_candidate'},
        dict(request=SimpleNamespace(get_json=lambda **kwargs:{'game_ids':[2],'dates':['20261102']}),
             db=SimpleNamespace(session=session),text=text,bindparam=bindparam,
             AvailableGame=SimpleNamespace(query=game_query,id=Mock()),
             time=SimpleNamespace(time=lambda:1,perf_counter=lambda:1),
             _slots_batch_cache_lock=threading.Lock(),_slots_batch_cache={},SLOTS_BATCH_CACHE_TTL_SEC=0,
             _ensure_slots_for_date=lambda *args:None,_force_slot_refresh=lambda:True,
             _load_booking_counts=lambda *args:{},_expected_blocks_for_date=lambda *args:None,
             jsonify=lambda data:SimpleNamespace(json=data,headers={}),current_app=SimpleNamespace(logger=Mock())))
    response,status=scope['get_slots_batch'](1)
    assert status==200,response.json
    assert response.json['20261102'][0]['available_slot']==0
    assert not response.json['20261102'][0]['is_available']
