import ast
from pathlib import Path
from datetime import date, datetime
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock
import sys
from flask import Flask, request, jsonify


def test_explicit_booking_retry_uses_original_day_and_does_not_write(monkeypatch):
    source=Path('controllers/booking_controller.py')
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='extra_booking')
    node.decorator_list=[]
    booking=SimpleNamespace(id=1084,user_id=1,game_id=2,slot_id=3)
    Booking=MagicMock();Booking.query.filter_by.return_value.populate_existing.return_value.with_for_update.return_value.first.return_value=booking
    Transaction=MagicMock();Transaction.query.filter_by.return_value.first.return_value=SimpleNamespace(id=50)
    db=MagicMock();db.session.query.return_value.filter_by.return_value.first.side_effect=[SimpleNamespace(id=1),SimpleNamespace(gaming_type_id=2)]
    db.session.query.return_value.filter_by.return_value.scalar.return_value=date(2026,10,2)
    games=MagicMock();games.query.filter_by.return_value.first.return_value=SimpleNamespace(id=2)
    module=ModuleType('services.payment_methods');module.require_method=MagicMock();monkeypatch.setitem(sys.modules,'services.payment_methods',module)
    scope=dict(request=request,jsonify=jsonify,datetime=datetime,db=db,Booking=Booking,Transaction=Transaction,
        User=MagicMock(),Slot=MagicMock(),AvailableGame=games,func=MagicMock(),g=SimpleNamespace(vendor_id=41),
        resolve_transaction_actor=lambda *a,**k:{'source_channel':'dashboard'},
        normalize_payment_use_case=lambda *a:'pending',resolve_settlement_status=lambda *a:'pending')
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    app=Flask(__name__)
    body=dict(consoleNumber=269,consoleType='PC',date='',slotId=3,userId=1,username='Guest',amount=10,gameId=2,
        modeOfPayment='pending',vendorId=41,booking_id=1084,reference_id='stable-retry')
    with app.test_request_context(json=body):
        response,status=scope['extra_booking']()
    assert status==200 and response.json['success']
    db.session.add.assert_not_called()
    db.session.execute.assert_not_called()


def test_accrued_settlement_does_not_require_pay_at_cafe(monkeypatch):
    source=Path('controllers/booking_controller.py')
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='settle_pending_booking_transactions')
    node.decorator_list=[]
    module=ModuleType('services.payment_methods');module.require_method=MagicMock(side_effect=ValueError('pay_at_cafe is disabled'))
    monkeypatch.setitem(sys.modules,'services.payment_methods',module)
    Booking=MagicMock();Booking.query.filter_by.return_value.first.return_value=None
    scope=dict(request=request,jsonify=jsonify,Booking=Booking,db=MagicMock(),current_app=MagicMock(),g=SimpleNamespace(vendor_id=41))
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    app=Flask(__name__)
    for mode in ('cash','card','upi','monthly_credit'):
        with app.test_request_context(json={'mode_of_payment':mode}):
            response,status=scope['settle_pending_booking_transactions'](999)
        assert status==404 and response.json['message']=='Booking not found'
    module.require_method.assert_not_called()


def test_payment_summary_is_not_cacheable():
    source=Path('controllers/booking_controller.py')
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='booking_payment_summary')
    node.decorator_list=[]
    Booking=MagicMock();Booking.query.filter_by.return_value.first.return_value=SimpleNamespace(squad_details={})
    scope=dict(Booking=Booking,jsonify=jsonify,current_app=MagicMock(),compute_booking_financial_summary=lambda _:dict(amount_due=20,amount_paid=10,total_charged=30))
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    app=Flask(__name__)
    with app.test_request_context():
        response,status=scope['booking_payment_summary'](1084)
    assert status==200 and response.json['payment_status']['amount_due']==20
    assert 'no-store' in response.headers['Cache-Control']


def _extra_booking_scope(monkeypatch, priced_quote, squad):
    import ast as _ast
    source=Path('controllers/booking_controller.py')
    node=next(n for n in _ast.parse(source.read_text()).body if isinstance(n,_ast.FunctionDef) and n.name=='extra_booking')
    node.decorator_list=[]
    booking=SimpleNamespace(id=1084,user_id=1,game_id=2,slot_id=3,squad_details=squad)
    Booking=MagicMock();Booking.query.filter_by.return_value.populate_existing.return_value.with_for_update.return_value.first.return_value=booking
    Transaction=MagicMock();Transaction.query.filter_by.return_value.first.return_value=None;Transaction.return_value.id=77
    db=MagicMock();db.session.query.return_value.filter_by.return_value.first.side_effect=[SimpleNamespace(id=1,contact_info=None),SimpleNamespace(gaming_type_id=2,start_time=None,end_time=None)]
    db.session.query.return_value.filter_by.return_value.scalar.return_value=date(2026,10,2)
    db.session.execute.return_value.scalar.return_value=None  # no kiosk runtime table
    games=MagicMock();games.query.filter_by.return_value.first.return_value=SimpleNamespace(id=2,game_name='PC')
    quote_module=ModuleType('services.overtime_quote')
    quote_module.quote=lambda *a,**k:dict(priced_quote)
    quote_module.parse_played_until=lambda v:None
    class OvertimeError(Exception):pass
    quote_module.OvertimeError=OvertimeError
    monkeypatch.setitem(sys.modules,'services.overtime_quote',quote_module)
    scope=dict(request=request,jsonify=jsonify,datetime=datetime,db=db,Booking=Booking,Transaction=Transaction,
        User=MagicMock(),Slot=MagicMock(),AvailableGame=games,func=MagicMock(),g=SimpleNamespace(vendor_id=41),
        resolve_transaction_actor=lambda *a,**k:{'source_channel':'dashboard','staff_id':None,'staff_name':None,'staff_role':None},
        normalize_payment_use_case=lambda *a:'pending',resolve_settlement_status=lambda *a:'pending',
        _overtime_squad_multiplier=lambda *a:3,_resolve_console_group=lambda *a,**k:'pc',
        _requires_multi_console_units=lambda *a,**k:True,resolve_app_fee_amount=lambda *a,**k:0,
        calculate_gst_breakdown=lambda v,a:dict(taxable_amount=a,gst_rate=0,cgst_amount=0,sgst_amount=0,igst_amount=0,total_with_tax=a),
        BookingService=MagicMock(),extra_booking_time_mail=MagicMock(),current_app=MagicMock(),
        text=lambda s:s,compute_booking_financial_summary=lambda _:dict(amount_due=0,amount_paid=0,total_charged=0))
    exec(compile(_ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    return scope,Transaction


def _charge(monkeypatch, priced_quote):
    scope,Transaction=_extra_booking_scope(monkeypatch,priced_quote,{'player_count':3,'enabled':True})
    body=dict(consoleNumber=269,consoleType='PC',date='',slotId=3,userId=1,username='Guest',gameId=2,
        modeOfPayment='pending',vendorId=41,booking_id=1084)
    with Flask(__name__).test_request_context(json=body):
        response,status=scope['extra_booking']()
    assert status==201, response.json
    return Transaction.call_args.kwargs['amount']


def test_rate_card_overtime_for_pc_squad_is_not_multiplied_again(monkeypatch):
    # The rate card already priced the whole three-player squad at Rs 150.
    assert _charge(monkeypatch,dict(amount=150,needs_end_time=False,amount_covers_squad=True,pricing_source='rate_card'))==150


def test_slot_rate_overtime_for_pc_squad_is_still_per_player(monkeypatch):
    assert _charge(monkeypatch,dict(amount=60,needs_end_time=False,pricing_source='slot_rate'))==180
