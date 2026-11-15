"""Opt-in café automations sharing HFG's sender and prepaid outbox."""
import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from db.extensions import db
from services.whatsapp import templates, phone, configured
from services.whatsapp_billing import credit

DEFAULTS={'confirmations':False,'reminders':False,'updates':False,'promotions':False,'booking_link':False,
          'reminder_minutes':60,'confirmation_template':'','reminder_template':'','booking_template':'','booking_url':''}
TOKENS={'customer','cafe','booking_id','date','time','date and time','booking_url'}


def preferences(vendor):
    row=db.session.execute(text('SELECT preferences FROM whatsapp_cafe_settings WHERE vendor_id=:v'),{'v':vendor}).first()
    return {**DEFAULTS,**(row[0] if row else {})}


def enqueue(vendor,recipient,template,values,key,note,purpose="updates",expires_at=None):
    mid=str(uuid.uuid5(uuid.NAMESPACE_URL,'hfg-whatsapp:'+key))
    db.session.execute(text('SELECT id FROM vendors WHERE id=:v FOR UPDATE'),{'v':vendor})
    if db.session.execute(text('SELECT 1 FROM whatsapp_outbox WHERE id=:id'),{'id':mid}).first():return
    if db.session.execute(text('SELECT 1 FROM whatsapp_optouts WHERE recipient=:p'),{'p':recipient}).first():return
    if not credit(vendor,-1,'send:'+mid):return
    db.session.execute(text('''INSERT INTO whatsapp_outbox(id,vendor_id,recipient,template,language,parameters,consent_note,actor,purpose,expires_at)
        VALUES(:id,:v,:p,:t,:l,CAST(:params AS jsonb),:note,'automation',:purpose,:expires_at)'''),
        dict(id=mid,v=vendor,p=recipient,t=template['name'],l=template['language'],params=json.dumps(values),note=note,purpose=purpose,expires_at=expires_at))


def selected_template(key):
    return next((t for t in templates() if t['name']+':'+t['language']==key),None)


def automate_bookings():
    if not configured():return
    policies=db.session.execute(text('SELECT vendor_id,enabled_since FROM whatsapp_cafe_settings')).mappings().all()
    now=datetime.now(ZoneInfo('Asia/Kolkata')).replace(tzinfo=None)
    for policy in policies:
        vendor=policy['vendor_id'];prefs=preferences(vendor)
        if not (prefs['confirmations'] or prefs['reminders']):continue
        # Persisted confirmed bookings only; pending payments never trigger confirmations.
        rows=db.session.execute(text('''SELECT DISTINCT ON (b.id) b.id,b.created_at,u.name,ci.phone,v.cafe_name,
            t.booked_date,COALESCE(b.custom_start_time,s.start_time) AS start_time
            FROM bookings b JOIN available_games a ON a.id=b.game_id JOIN vendors v ON v.id=a.vendor_id
            JOIN users u ON u.id=b.user_id JOIN contact_info ci ON ci.parent_id=u.id AND ci.parent_type='user'
            JOIN transactions t ON t.booking_id=b.id AND t.vendor_id=a.vendor_id
            LEFT JOIN slots s ON s.id=b.slot_id
            WHERE a.vendor_id=:v AND b.status='confirmed'
              AND t.booked_date BETWEEN (now() AT TIME ZONE 'Asia/Kolkata')::date AND (now() AT TIME ZONE 'Asia/Kolkata')::date+3
            ORDER BY b.id,t.id DESC LIMIT 1000'''),{'v':vendor}).mappings().all()
        for row in rows:
            try:
                recipient=phone(row['phone'])
                if len(recipient)==10:recipient='91'+recipient
            except ValueError:continue
            contact=db.session.execute(text('SELECT consent_note FROM whatsapp_contacts WHERE vendor_id=:v AND recipient=:p AND service_consent=true'),{'v':vendor,'p':recipient}).first()
            if not contact or not row['start_time']:continue
            start=datetime.combine(row['booked_date'],row['start_time'])
            tokens={'customer':row['name'],'cafe':row['cafe_name'],'booking_id':str(row['id']),
                'date':str(row['booked_date']),'time':str(row['start_time']),
                'date and time':str(start),'booking_url':prefs['booking_url']}
            for kind in ('confirmation','reminder'):
                if kind=='confirmation' and not (prefs['confirmations'] and row['created_at']>=policy['enabled_since'] and start>now):continue
                if kind=='reminder' and not (prefs['reminders'] and 0<(start-now).total_seconds()<=prefs['reminder_minutes']*60):continue
                template=selected_template(prefs[kind+'_template'])
                if not template:continue
                values=[str(tokens.get(field.lower(),'')) for field in template['fields']]
                if any(not v for v in values):continue
                enqueue(vendor,recipient,template,values,f'{kind}:{vendor}:{row["id"]}',contact[0],purpose='confirmations' if kind=='confirmation' else 'reminders',expires_at=start.replace(tzinfo=ZoneInfo('Asia/Kolkata')))
                db.session.commit()


def booking_enquiry(item):
    """Explicit cafe keyword avoids guessing recipients across the shared HFG number."""
    import re
    match=re.fullmatch(r'BOOK\s+(\d+)',str(item.get('text',{}).get('body','')).strip(),re.I)
    if not match:return
    vendor=int(match.group(1));prefs=preferences(vendor)
    if not prefs['booking_link']:return
    template=selected_template(prefs['booking_template'])
    if not template:return
    recipient=phone(item.get('from'))
    if db.session.execute(text("SELECT 1 FROM whatsapp_outbox WHERE vendor_id=:v AND recipient=:p AND purpose='booking_link' AND created_at>now()-interval '1 hour'"),{'v':vendor,'p':recipient}).first():return
    cafe=db.session.execute(text('SELECT cafe_name FROM vendors WHERE id=:v'),{'v':vendor}).scalar()
    if not cafe:return
    tokens={'booking_url':prefs['booking_url'],'cafe':cafe}
    values=[tokens.get(field.lower(),'') for field in template['fields']]
    if any(not v for v in values):return
    enqueue(vendor,recipient,template,values,'inbound:'+str(item.get('id')),'Customer requested a booking link with BOOK keyword.',purpose='booking_link')
