import os
import uuid
import hmac
import hashlib
from functools import wraps
import razorpay
from flask import Blueprint,request,jsonify,current_app
from sqlalchemy import text
from db.extensions import db
from services.vendor_access import require_vendor_permission
from services.whatsapp import settings,configured
from services.whatsapp_billing import read_config,save_config,SECRET_FIELDS,grant_purchase

whatsapp_payments=Blueprint('whatsapp_payments',__name__)

@whatsapp_payments.after_request
def no_cache(response):
    response.headers['Cache-Control']='no-store'
    return response


def admin(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        expected=os.getenv('SUPER_ADMIN_API_KEY','')
        if not expected or not hmac.compare_digest(expected,request.headers.get('x-admin-key','')):
            return jsonify(error='Super-admin authorization required'),401
        return fn(*args,**kwargs)
    return wrapped


@whatsapp_payments.route('/admin/whatsapp/config',methods=['GET','PUT'])
@admin
def config():
    warning=None
    if request.method=='PUT':
        try:warning=save_config(request.get_json(silent=True) or {})
        except ValueError as error:return jsonify(error=str(error)),400
        except (TypeError,KeyError):return jsonify(error='Invalid WhatsApp settings. Check the price, sender details and templates.'),400
    try:values=read_config()
    except ValueError as error:return jsonify(error=str(error)),503
    except KeyError:return jsonify(error='WhatsApp settings cannot be read. Check the booking service encryption key configuration.'),503
    public={k:v for k,v in values.items() if k not in SECRET_FIELDS}
    public['configured_secrets']={k:bool(values.get(k)) for k in SECRET_FIELDS}
    if warning:public['warning']=warning
    return jsonify(public)


@whatsapp_payments.get('/admin/whatsapp/wallets')
@admin
def wallets():
    rows=db.session.execute(text('SELECT w.vendor_id,v.cafe_name,w.credits FROM whatsapp_wallet w JOIN vendors v ON v.id=w.vendor_id ORDER BY w.vendor_id')).mappings()
    return jsonify(wallets=[dict(r) for r in rows])


def gateway():
    key=current_app.config.get('RAZORPAY_KEY_ID')
    secret=current_app.config.get('RAZORPAY_KEY_SECRET')
    if not key or not secret:raise ValueError('Online payments are not configured.')
    return razorpay.Client(auth=(key,secret)),key


@whatsapp_payments.post('/vendor/<int:vendor_id>/whatsapp/orders')
@require_vendor_permission('account.manage')
def create_pack_order(vendor_id):
    if not configured():return jsonify(error='WhatsApp is not enabled yet.'),503
    body=request.get_json(silent=True) or {}
    try:
        purchase_id=str(uuid.UUID(str(body.get('idempotency_key'))))
        price=int(settings().get('PACK_PRICE_PAISE') or 0)
        if not 100<=price<=10000000:raise ValueError('Pack price is not configured.')
        client,key=gateway()
    except (ValueError,TypeError):return jsonify(error='Invalid order request or payment configuration.'),400
    # Persist before calling provider: an uncertain response never silently creates another order.
    db.session.execute(text('SELECT id FROM vendors WHERE id=:v FOR UPDATE'),{'v':vendor_id})
    row=db.session.execute(text('SELECT * FROM whatsapp_purchases WHERE id=:id'),{'id':purchase_id}).mappings().first()
    if row:
        if row['vendor_id']!=vendor_id:return jsonify(error='Order belongs to another cafe.'),403
        if not row['order_id']:return jsonify(error='Order creation is pending or uncertain. Contact HFG support.'),409
        return jsonify(order_id=row['order_id'],amount=row['amount_paise'],currency='INR',key_id=key,paid=row['status']=='paid')
    recent=db.session.execute(text("SELECT count(*) FROM whatsapp_purchases WHERE vendor_id=:v AND created_at>now()-interval '1 hour'"),{'v':vendor_id}).scalar()
    if recent>=10:return jsonify(error='Too many payment attempts. Please try later.'),429
    db.session.execute(text('INSERT INTO whatsapp_purchases(id,vendor_id,amount_paise) VALUES(:id,:v,:a)'),dict(id=purchase_id,v=vendor_id,a=price))
    db.session.commit()
    try:
        order=client.order.create({'amount':price,'currency':'INR','receipt':purchase_id,'notes':{'purpose':'whatsapp_pack','vendor_id':str(vendor_id)}})
        db.session.execute(text('UPDATE whatsapp_purchases SET order_id=:o WHERE id=:id'),dict(o=order['id'],id=purchase_id))
        db.session.commit()
        return jsonify(order_id=order['id'],amount=price,currency='INR',key_id=key),201
    except Exception:
        db.session.rollback()
        return jsonify(error='Could not confirm payment order creation. Contact HFG support before retrying.'),502


@whatsapp_payments.post('/vendor/<int:vendor_id>/whatsapp/payments/verify')
@require_vendor_permission('account.manage')
def verify_pack_payment(vendor_id):
    body=request.get_json(silent=True) or {}
    try:
        client,_=gateway()
        client.utility.verify_payment_signature({k:body[k] for k in ('razorpay_order_id','razorpay_payment_id','razorpay_signature')})
        added=grant_purchase(client,body['razorpay_order_id'],body['razorpay_payment_id'],vendor_id)
        return jsonify(activated=True,credits_added=100 if added else 0)
    except Exception:
        db.session.rollback()
        return jsonify(error='Payment not yet verified. Credits activate only after capture; refresh shortly or contact HFG support.'),409


@whatsapp_payments.post('/whatsapp/payment-webhook')
def payment_webhook():
    secret=settings().get('PAYMENT_WEBHOOK_SECRET','')
    expected=hmac.new(secret.encode(),request.get_data(),hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(expected,request.headers.get('X-Razorpay-Signature','')):return '',403
    db.session.execute(text("INSERT INTO whatsapp_provider_checks(name) VALUES('razorpay_signed_callback') ON CONFLICT(name) DO UPDATE SET observed_at=now()"))
    db.session.commit()
    body=request.get_json(silent=True) or {}
    if body.get('event')=='payment.captured':
        payment=body.get('payload',{}).get('payment',{}).get('entity',{})
        order_id=payment.get('order_id')
        # Ignore other products on the shared HFG payment account.
        if db.session.execute(text('SELECT 1 FROM whatsapp_purchases WHERE order_id=:o'),{'o':order_id}).first():
            try:
                client,_=gateway()
                grant_purchase(client,order_id,payment.get('id'))
            except Exception:
                db.session.rollback()
                return '',503
    return '',200
