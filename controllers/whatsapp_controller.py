import uuid
import json
import hmac
from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from db.extensions import db
from services.vendor_access import require_vendor_permission
from services.whatsapp_billing import credit, refund_message
from services.whatsapp import settings, configured, templates, phone, valid_signature, process_one

whatsapp = Blueprint('whatsapp', __name__)


@whatsapp.get('/vendor/<int:vendor_id>/whatsapp')
@require_vendor_permission('account.manage')
def whatsapp_status(vendor_id):
    rows = db.session.execute(text("""SELECT id,recipient,template,status,error,created_at
        FROM whatsapp_outbox WHERE vendor_id=:v ORDER BY created_at DESC LIMIT 50"""),{'v':vendor_id}).mappings()
    balance=db.session.execute(text('SELECT credits FROM whatsapp_wallet WHERE vendor_id=:v'),{'v':vendor_id}).scalar() or 0
    ledger=db.session.execute(text('SELECT delta,reference,created_at FROM whatsapp_credit_ledger WHERE vendor_id=:v ORDER BY id DESC LIMIT 30'),{'v':vendor_id}).mappings().all()
    response = jsonify(ledger=[dict(r) for r in ledger],credits=balance,pack_price_paise=int(settings().get('PACK_PRICE_PAISE') or 0),pack_size=100,sender='Hash for Gamers',configured=bool(configured()),templates=templates(),
        messages=[dict(r, id=str(r['id']), recipient='••••'+r['recipient'][-4:]) for r in rows])
    response.headers['Cache-Control']='no-store'
    return response


@whatsapp.post('/vendor/<int:vendor_id>/whatsapp/messages')
@require_vendor_permission('account.manage')
def queue_whatsapp(vendor_id):
    if not configured():
        return jsonify(error='WhatsApp is not configured. Contact the HFG administrator.'),503
    body=request.get_json(silent=True) or {}
    from services.whatsapp_automation import preferences
    prefs=preferences(vendor_id)
    purpose=body.get('purpose','updates')
    if purpose not in ('updates','promotions') or not prefs[purpose]:
        return jsonify(error='Enable this message purpose in cafe WhatsApp settings first.'),409
    try:
        message_id=str(uuid.UUID(str(body.get('idempotency_key'))))
        recipient=phone(body.get('recipient'))
        template=next((t for t in templates() if t['name']==body.get('template') and t['language']==body.get('language')),None)
        values=body.get('parameters')
        note=body.get('consent_note')
        if not template or not isinstance(values,list) or len(values)!=len(template['fields']) or any(not isinstance(v,str) or not v.strip() or len(v)>500 for v in values):
            raise ValueError('Choose a configured template and fill every field (maximum 500 characters).')
        if body.get('consent') is not True or not isinstance(note,str) or not 3<=len(note.strip())<=500:
            raise ValueError('Record how and when this customer agreed to receive messages.')
    except (ValueError,TypeError,AttributeError) as error:
        return jsonify(error=str(error)),400
    if purpose=='promotions':
        allowed=db.session.execute(text('SELECT 1 FROM whatsapp_contacts WHERE vendor_id=:v AND recipient=:p AND marketing_consent=true'),{'v':vendor_id,'p':recipient}).first()
        if not allowed:return jsonify(error='Record separate marketing consent for this customer first.'),409
    existing=db.session.execute(text('SELECT vendor_id,recipient,template,language,parameters FROM whatsapp_outbox WHERE id=:id'),{'id':message_id}).first()
    if existing:
        if existing[0]!=vendor_id:return jsonify(error='Message key is already in use.'),409
        if (existing[1],existing[2],existing[3],existing[4])!=(recipient,template['name'],template['language'],values):
            return jsonify(error='Message key was used for different content. Refresh before sending.'),409
        return jsonify(id=message_id,queued=True),200
    if db.session.execute(text('SELECT 1 FROM whatsapp_optouts WHERE recipient=:p'),{'p':recipient}).first():
        return jsonify(error='This customer opted out of HFG WhatsApp messages.'),409
    # Serialize per-cafe limits even when multiple dashboard requests arrive together.
    db.session.execute(text('SELECT id FROM vendors WHERE id=:v FOR UPDATE'),{'v':vendor_id})
    count=db.session.execute(text("SELECT count(*) FROM whatsapp_outbox WHERE vendor_id=:v AND created_at>now()-interval '1 hour'"),{'v':vendor_id}).scalar()
    if count>=100:return jsonify(error='Hourly message limit reached. Please try later.'),429
    if not credit(vendor_id,-1,'send:'+message_id):
        db.session.rollback()
        return jsonify(error='Buy a message pack to activate WhatsApp sending.'),402
    db.session.execute(text("""INSERT INTO whatsapp_outbox(id,vendor_id,recipient,template,language,parameters,consent_note,actor,purpose)
        VALUES(:id,:v,:p,:t,:l,CAST(:params AS jsonb),:note,:actor,:purpose) ON CONFLICT(id) DO NOTHING"""),
        dict(id=message_id,v=vendor_id,p=recipient,t=template['name'],l=template['language'],params=json.dumps(values),note=note.strip(),
             purpose=purpose,actor=str((g.vendor_claims.get('staff') or {}).get('id') or 'owner')))
    db.session.commit()
    return jsonify(id=message_id,queued=True),202


@whatsapp.route('/whatsapp/webhook',methods=['GET','POST'])
def whatsapp_webhook():
    c=settings()
    if request.method=='GET':
        if c['VERIFY_TOKEN'] and request.args.get('hub.mode')=='subscribe' and hmac.compare_digest(request.args.get('hub.verify_token',''),c['VERIFY_TOKEN']):
            db.session.execute(text("INSERT INTO whatsapp_provider_checks(name) VALUES('meta_verification') ON CONFLICT(name) DO UPDATE SET observed_at=now()"))
            db.session.commit()
            return request.args.get('hub.challenge',''),200
        return '',403
    if not valid_signature(request.get_data(),request.headers.get('X-Hub-Signature-256')):
        return '',403
    body=request.get_json(silent=True) or {}
    for entry in body.get('entry',[]):
        for change in entry.get('changes',[]):
            value=change.get('value',{})
            if value.get('metadata',{}).get('phone_number_id')!=c['PHONE_NUMBER_ID']:continue
            db.session.execute(text("INSERT INTO whatsapp_provider_checks(name) VALUES('meta_signed_callback') ON CONFLICT(name) DO UPDATE SET observed_at=now()"))
            for item in value.get('statuses',[]):
                state=item.get('status')
                if state not in ('sent','delivered','read','failed'):continue
                db.session.execute(text("""UPDATE whatsapp_outbox SET status=:state,provider_id=COALESCE(provider_id,:pid),
                    error=CASE WHEN :state='failed' THEN 'WhatsApp delivery failed.' ELSE NULL END,updated_at=now()
                    WHERE (provider_id=:pid OR id::text=:callback)
                    AND status NOT IN ('read','suppressed','failed')
                    AND (status!='delivered' OR :state='read')"""),
                    dict(state=state,pid=item.get('id'),callback=item.get('biz_opaque_callback_data','')))
                if state=='failed':
                    failed=db.session.execute(text("SELECT id FROM whatsapp_outbox WHERE provider_id=:p AND status='failed'"),{'p':item.get('id')}).first()
                    if failed:refund_message(failed[0])
            for item in value.get('messages',[]):
                from services.whatsapp_automation import booking_enquiry
                booking_enquiry(item)
                if str(item.get('text',{}).get('body','')).strip().lower() in ('stop','unsubscribe','stop all'):
                    try:recipient=phone(item.get('from'))
                    except ValueError:continue
                    db.session.execute(text('INSERT INTO whatsapp_optouts(recipient) VALUES(:p) ON CONFLICT DO NOTHING'),{'p':recipient})
    db.session.commit()
    return '',200


def register_whatsapp(app):
    app.register_blueprint(whatsapp,url_prefix='/api')
    @app.cli.command('whatsapp-dispatch')
    def dispatch():
        """Dispatch up to 100 queued messages. Schedule every minute."""
        from services.whatsapp_automation import automate_bookings
        db.session.execute(text("UPDATE whatsapp_outbox SET status='unknown',error='Dispatch interrupted. Inspect Meta before resending.',updated_at=now() WHERE status='sending' AND updated_at<now()-interval '5 minutes'"))
        db.session.commit()
        automate_bookings()
        for _ in range(100):
            if not process_one():break
