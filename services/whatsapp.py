"""Single HFG sender. Durable outbox; no browser access to Meta credentials."""
import os
import re
import json
import hmac
import hashlib
import requests
from sqlalchemy import text
from db.extensions import db


def settings():
    from services.whatsapp_billing import read_config
    values = {key: os.getenv('WHATSAPP_' + key, '') for key in
            ('ENABLED','PHONE_NUMBER_ID','ACCESS_TOKEN','APP_SECRET','VERIFY_TOKEN','API_VERSION','TEMPLATES','PACK_PRICE_PAISE','PAYMENT_WEBHOOK_SECRET')}
    values.update(read_config())
    return values


def configured():
    c = settings()
    return c['ENABLED'].lower() == 'true' and all(c[k] for k in
        ('PHONE_NUMBER_ID','ACCESS_TOKEN','APP_SECRET','VERIFY_TOKEN','API_VERSION'))


def templates():
    # Explicit allowlist: [{name, language, fields: [label,...]}]. No arbitrary templates.
    rows = json.loads(settings()['TEMPLATES'] or '[]')
    if not isinstance(rows, list):
        raise ValueError('Invalid WhatsApp template configuration')
    for row in rows:
        if not re.fullmatch(r'[a-z0-9_]+', row['name']) or not re.fullmatch(r'[a-zA-Z_]+', row['language']):
            raise ValueError('Invalid WhatsApp template configuration')
        if not isinstance(row['fields'], list) or any(not isinstance(f,str) for f in row['fields']):
            raise ValueError('Invalid template fields')
    return rows


def phone(value):
    normalized = re.sub(r'[\s()+-]', '', str(value or ''))
    if not re.fullmatch(r'[1-9][0-9]{7,14}', normalized):
        raise ValueError('Enter a phone number with country code, for example +919876543210.')
    return normalized


def valid_signature(raw, signature):
    secret = settings()['APP_SECRET']
    expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature or '')


def process_one():
    if not configured():
        return False
    row = db.session.execute(text("""SELECT * FROM whatsapp_outbox
        WHERE status='queued' AND next_attempt<=now()
        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""")).mappings().first()
    if not row:
        db.session.rollback()
        return False
    row = dict(row)
    opted_out = db.session.execute(text('SELECT 1 FROM whatsapp_optouts WHERE recipient=:recipient'),row).first()
    from services.whatsapp_automation import preferences
    from datetime import datetime, timezone
    policy = preferences(row['vendor_id'])
    suppressed = not policy.get(row['purpose'], False)
    if row.get('expires_at') and row['expires_at'] <= datetime.now(timezone.utc):
        suppressed = True
    if row['purpose'] in ('promotions','confirmations','reminders'):
        column = 'marketing_consent' if row['purpose']=='promotions' else 'service_consent'
        consent = db.session.execute(text(f'SELECT 1 FROM whatsapp_contacts WHERE vendor_id=:v AND recipient=:p AND {column}=true'), {'v':row['vendor_id'],'p':row['recipient']}).first()
        suppressed = suppressed or not consent
    if opted_out or suppressed:
        db.session.execute(text("UPDATE whatsapp_outbox SET status='suppressed',updated_at=now() WHERE id=:id"),row)
        from services.whatsapp_billing import refund_message
        refund_message(row['id'])
        db.session.commit()
        return True
    db.session.execute(text("UPDATE whatsapp_outbox SET status='sending',attempts=attempts+1,updated_at=now() WHERE id=:id"),row)
    db.session.commit()
    c = settings()
    payload = {'messaging_product':'whatsapp','to':row['recipient'],'type':'template',
        'biz_opaque_callback_data':str(row['id']),
        'template':{'name':row['template'],'language':{'code':row['language']}}}
    if row['parameters']:
        payload['template']['components'] = [{'type':'body','parameters':[
            {'type':'text','text':value} for value in row['parameters']]}]
    status, provider, error = 'unknown', None, 'Delivery outcome unknown; inspect Meta before resending.'
    try:
        response = requests.post(f"https://graph.facebook.com/{c['API_VERSION']}/{c['PHONE_NUMBER_ID']}/messages",
            headers={'Authorization':f"Bearer {c['ACCESS_TOKEN']}"},json=payload,timeout=20)
        if response.ok:
            provider = response.json()['messages'][0]['id']
            status, error = 'sent', None
        elif response.status_code == 429 and row['attempts'] < 4:
            status, error = 'queued', 'Meta rate limit; queued for retry.'
        else:
            status, error = 'failed', f'Meta rejected message (HTTP {response.status_code}). Check template and sender configuration.'
    except (requests.RequestException, ValueError, KeyError, IndexError):
        # A timeout can mean Meta accepted it. Never automatically duplicate a message.
        pass
    updated = db.session.execute(text("""UPDATE whatsapp_outbox SET status=:status,provider_id=COALESCE(provider_id,:provider),
        error=:error,updated_at=now(),next_attempt=now()+interval '5 minutes'
        WHERE id=:id AND status='sending'"""),dict(id=row['id'],status=status,provider=provider,error=error))
    if status == 'failed' and updated.rowcount:
        from services.whatsapp_billing import refund_message
        refund_message(row['id'])
    db.session.commit()
    return True
