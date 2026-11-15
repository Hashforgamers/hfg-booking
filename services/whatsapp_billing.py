"""Prepaid credits: all grants verified server-side and ledger entries idempotent."""
import os
import json
from cryptography.fernet import Fernet
from sqlalchemy import text
from db.extensions import db

SECRET_FIELDS={'ACCESS_TOKEN','APP_SECRET','VERIFY_TOKEN','PAYMENT_WEBHOOK_SECRET'}
CONFIG_FIELDS=SECRET_FIELDS|{'ENABLED','PHONE_NUMBER_ID','API_VERSION','TEMPLATES','PACK_PRICE_PAISE','WABA_ID'}


def read_config():
    row=db.session.execute(text('SELECT values_encrypted FROM whatsapp_config WHERE id=1')).first()
    if not row:return {}
    return json.loads(Fernet(os.environ['WHATSAPP_CONFIG_KEY'].encode()).decrypt(row[0].encode()))


def save_config(values):
    if not os.getenv('WHATSAPP_CONFIG_KEY'):raise ValueError('Set WHATSAPP_CONFIG_KEY on the booking server before saving credentials.')
    unknown=set(values)-CONFIG_FIELDS
    if unknown:raise ValueError('Unknown configuration field')
    merged=read_config()
    for key,value in values.items():
        if key in SECRET_FIELDS and not value:continue
        merged[key]=str(value)
    price=merged.get('PACK_PRICE_PAISE','0')
    if not price.isdigit() or not 100<=int(price)<=10000000:raise ValueError('Pack price must be between ₹1 and ₹100,000.')
    import re
    if merged.get('PHONE_NUMBER_ID') and not re.fullmatch(r'\d+',merged['PHONE_NUMBER_ID']):raise ValueError('Phone number ID must be numeric.')
    if merged.get('API_VERSION') and not re.fullmatch(r'v\d+\.\d+',merged['API_VERSION']):raise ValueError('Enter a Meta API version such as v27.0.')
    if merged.get('WABA_ID') and not merged['WABA_ID'].isdigit():raise ValueError('WABA ID must be numeric.')
    if merged.get('API_VERSION') and int(merged['API_VERSION'].split('.')[0][1:])<20:raise ValueError('Choose a currently supported Meta API version, not v1.0.')
    rows=json.loads(merged.get('TEMPLATES') or '[]')
    if not isinstance(rows,list) or len(rows)>30:raise ValueError('Provide up to 30 templates.')
    for row in rows:
        if not isinstance(row,dict) or not re.fullmatch(r'[a-z0-9_]+',str(row.get('name',''))) or not re.fullmatch(r'[A-Za-z_]+',str(row.get('language',''))) or not isinstance(row.get('fields'),list) or len(row['fields'])>20 or any(not isinstance(f,str) or not f.strip() or len(f)>100 for f in row['fields']):raise ValueError('Invalid template name, language or field labels.')
    if merged.get('ENABLED','false').lower() not in ('true','false'):raise ValueError('Choose enabled or disabled.')
    if merged.get('ENABLED','false').lower()=='true' and (not rows or not all(merged.get(k) for k in ('ACCESS_TOKEN','APP_SECRET','VERIFY_TOKEN','PHONE_NUMBER_ID','API_VERSION'))):raise ValueError('Complete sender credentials and templates before enabling.')
    encrypted=Fernet(os.environ['WHATSAPP_CONFIG_KEY'].encode()).encrypt(json.dumps(merged).encode()).decode()
    db.session.execute(text("INSERT INTO whatsapp_config(id,values_encrypted) VALUES(1,:v) ON CONFLICT(id) DO UPDATE SET values_encrypted=:v,updated_at=now()"),{'v':encrypted})
    db.session.commit()


def credit(vendor_id,delta,reference):
    db.session.execute(text('INSERT INTO whatsapp_wallet(vendor_id) VALUES(:v) ON CONFLICT DO NOTHING'),{'v':vendor_id})
    balance=db.session.execute(text('SELECT credits FROM whatsapp_wallet WHERE vendor_id=:v FOR UPDATE'),{'v':vendor_id}).scalar()
    if db.session.execute(text('SELECT 1 FROM whatsapp_credit_ledger WHERE reference=:r'),{'r':reference}).first():return True
    if balance+delta<0:return False
    db.session.execute(text('INSERT INTO whatsapp_credit_ledger(vendor_id,delta,reference) VALUES(:v,:d,:r)'),{'v':vendor_id,'d':delta,'r':reference})
    db.session.execute(text('UPDATE whatsapp_wallet SET credits=credits+:d WHERE vendor_id=:v'),{'v':vendor_id,'d':delta})
    return True


def refund_message(message_id):
    row=db.session.execute(text('SELECT vendor_id FROM whatsapp_outbox WHERE id=:id'),{'id':message_id}).first()
    if row and db.session.execute(text('SELECT 1 FROM whatsapp_credit_ledger WHERE reference=:r'),{'r':'send:'+str(message_id)}).first():
        credit(row[0],1,'refund:'+str(message_id))


def grant_purchase(client,order_id,payment_id,vendor_id=None):
    purchase=db.session.execute(text('SELECT * FROM whatsapp_purchases WHERE order_id=:o FOR UPDATE'),{'o':order_id}).mappings().first()
    if not purchase or (vendor_id is not None and purchase['vendor_id']!=vendor_id):raise ValueError('Purchase not found for this cafe.')
    if purchase['status']=='paid':
        db.session.commit()
        return False
    payment=client.payment.fetch(payment_id)
    if payment.get('status')!='captured' or payment.get('order_id')!=order_id or payment.get('currency')!='INR' or payment.get('amount')!=purchase['amount_paise']:
        raise ValueError('Payment is not captured or does not match this pack.')
    credit(purchase['vendor_id'],100,'purchase:'+str(purchase['id']))
    db.session.execute(text("UPDATE whatsapp_purchases SET status='paid',payment_id=:p,paid_at=now() WHERE id=:id"),{'p':payment_id,'id':purchase['id']})
    db.session.commit()
    return True
