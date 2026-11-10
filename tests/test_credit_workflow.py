import importlib.util
from pathlib import Path
from datetime import date
from types import SimpleNamespace
import pytest
spec=importlib.util.spec_from_file_location('credit_workflow',Path(__file__).resolve().parents[1]/'services/credit_workflow.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
@pytest.mark.parametrize('value',['NaN','Infinity',-1,True,'1.001','abc'])
def test_invalid_money_rejected(value):
    with pytest.raises(ValueError):module.amount(value)

def test_limits_and_sensitive_field_validation():
    valid=dict(credit_limit=500,billing_cycle_day=1,grace_days=0,is_active=True,email='player@example.com')
    assert module.validate_account(valid,159)==(500,1,0)
    for changes in [dict(credit_limit=100),dict(billing_cycle_day=29),dict(grace_days=-1),dict(is_active='yes'),dict(email='invalid'),dict(id_proof_number='x'*101),dict(phone_number='letters')]:
        with pytest.raises(ValueError):module.validate_account({**valid,**changes},159)

def test_due_is_distinct_from_total_outstanding():
    entries=[SimpleNamespace(entry_type='charge',amount=100,due_date=date(2030,1,1)),SimpleNamespace(entry_type='charge',amount=80,due_date=date(2030,2,1)),SimpleNamespace(entry_type='payment',amount=30,due_date=None)]
    assert module.amount_due(entries,150,date(2030,1,15))==70
    assert module.amount_due(entries,150,date(2030,2,15))==150
    assert module.amount_due(entries,50,date(2030,2,15))==50
    entries.append(SimpleNamespace(entry_type='adjustment',amount=-20,due_date=date(2030,1,15)))
    assert module.amount_due(entries,130,date(2030,1,15))==50

# Exercise production route validation without booting external services.
import ast
from flask import Flask, jsonify, request
from unittest.mock import Mock

def route(name,account):
    source=Path(__file__).resolve().parents[1]/'controllers/booking_controller.py'
    tree=ast.parse(source.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);fn.decorator_list=[]
    query=Mock();query.filter_by.return_value=query;query.with_for_update.return_value=query;query.first.return_value=account
    scope=dict(request=request,jsonify=jsonify,MonthlyCreditAccount=SimpleNamespace(query=query),db=SimpleNamespace(session=Mock()))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(source),'exec'),scope)
    return scope[name],scope

@pytest.mark.parametrize('body,message',[
    ({'user_id':1,'amount':20,'confirmed':True},'exceeds'),
    ({'user_id':1,'amount':'NaN','confirmed':True},'valid amount'),
    ({'user_id':1,'amount':5},'Confirm'),
    ({'user_id':1,'amount':5,'confirmed':True,'mode_of_payment':'Other'},'method'),
])
def test_payment_rejects_overpayment_invalid_money_and_missing_confirmation(body,message):
    app=Flask(__name__);fn,scope=route('settle_monthly_credit',SimpleNamespace(outstanding_amount=16))
    with app.test_request_context(json=body):
        response,status=fn(1)
        assert status==400 and message in response.json['message']
        scope['db'].session.add.assert_not_called()

@pytest.mark.parametrize('change,reason,confirmed',[(501,'Correction',True),(-17,'Correction',True),(1,'x',True),(1,'Correction',False)])
def test_adjustment_rejects_unsafe_balances_and_missing_reason(change,reason,confirmed):
    app=Flask(__name__);fn,scope=route('adjust_monthly_credit',SimpleNamespace(outstanding_amount=16,credit_limit=500))
    with app.test_request_context(json=dict(user_id=1,amount=change,reason=reason,confirmed=confirmed)):
        response,status=fn(1)
        assert status==400
        scope['db'].session.add.assert_not_called()
