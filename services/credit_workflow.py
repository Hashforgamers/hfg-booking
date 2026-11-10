"""Validation and balance labels shared by the credit management workflow."""
from decimal import Decimal, InvalidOperation
from datetime import date
import re

def amount(value, *, positive=False, signed=False):
    try:
        if isinstance(value,bool):raise ValueError()
        result=Decimal(str(value))
        if not result.is_finite() or abs(result)>99999999 or result!=result.quantize(Decimal('.01')) or (not signed and result<0) or (positive and result<=0):raise ValueError()
        return float(result)
    except (InvalidOperation,ValueError,TypeError):raise ValueError('Enter a valid amount with up to two decimal places.')

SENSITIVE=('address_line1','address_line2','city','state','pincode','id_proof_type','id_proof_number')

def validate_account(body, outstanding=0):
    limit=amount(body['credit_limit'])
    if limit<outstanding:raise ValueError('Credit limit cannot be lower than the outstanding balance. Record a payment or adjustment first.')
    day=body.get('billing_cycle_day',1);grace=body.get('grace_days',5)
    if type(day) is not int or not 1<=day<=28:raise ValueError('Billing day must be from 1 to 28.')
    if type(grace) is not int or not 0<=grace<=90:raise ValueError('Grace period must be from 0 to 90 days.')
    if type(body.get('is_active',True)) is not bool:raise ValueError('Choose an account status.')
    for key in ('customer_name','whatsapp_number','phone_number','email','notes',*SENSITIVE):
        value=body.get(key)
        if value is not None and (not isinstance(value,str) or len(value)> {'notes':255,'phone_number':20,'whatsapp_number':20,'pincode':20,'id_proof_type':50,'city':100,'state':100,'id_proof_number':100}.get(key,255)):
            raise ValueError(f'Check {key.replace("_"," ")}.')
    if body.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',body['email']):raise ValueError('Enter a valid email address.')
    for key in ('phone_number','whatsapp_number'):
        if body.get(key) and not re.fullmatch(r'\+?[0-9 ()-]{7,20}',body[key]):raise ValueError('Enter a valid phone number.')
    return limit,day,grace

def amount_due(entries,outstanding,today=None):
    today=today or date.today()
    due=sum(float(e.amount or 0) for e in entries if e.entry_type in ('charge','adjustment') and e.due_date and e.due_date<=today)
    payments=sum(float(e.amount or 0) for e in entries if e.entry_type=='payment')
    return round(max(0,min(float(outstanding or 0),due-payments)),2)
