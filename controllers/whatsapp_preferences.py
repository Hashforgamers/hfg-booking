import json
from urllib.parse import urlparse
from flask import Blueprint,request,jsonify
from sqlalchemy import text
from db.extensions import db
from services.vendor_access import require_vendor_permission
from services.whatsapp import phone
from services.whatsapp_automation import DEFAULTS,TOKENS,preferences,selected_template

whatsapp_preferences=Blueprint('whatsapp_preferences',__name__)


@whatsapp_preferences.route('/vendor/<int:vendor_id>/whatsapp/preferences',methods=['GET','PUT'])
@require_vendor_permission('account.manage')
def cafe_preferences(vendor_id):
    if request.method=='PUT':
        body=request.get_json(silent=True) or {}
        try:
            if set(body)-set(DEFAULTS):raise ValueError('Unknown preference')
            prefs={**DEFAULTS,**body}
            for key in ('confirmations','reminders','updates','promotions','booking_link'):
                if type(prefs[key]) is not bool:raise ValueError('Invalid switch value')
            if type(prefs['reminder_minutes']) is not int or not 5<=prefs['reminder_minutes']<=1440:raise ValueError('Reminder lead time must be 5–1440 minutes.')
            url=urlparse(prefs['booking_url'])
            if prefs['booking_url'] and (url.scheme!='https' or not url.hostname or url.username):raise ValueError('Use a public HTTPS booking link.')
            for switch,key in [('confirmations','confirmation_template'),('reminders','reminder_template'),('booking_link','booking_template')]:
                if not prefs[switch]:continue
                t=selected_template(prefs[key]);allowed={'cafe','booking_url'} if switch=='booking_link' else TOKENS
                if not t or any(f.lower() not in allowed for f in t['fields']):raise ValueError('Choose a template with supported automation fields.')
                if ('booking_url' in [f.lower() for f in t['fields']] or switch=='booking_link') and not prefs['booking_url']:raise ValueError('Set the booking link first.')
            old=preferences(vendor_id)
            reset=not old['confirmations'] and prefs['confirmations']
            db.session.execute(text('''INSERT INTO whatsapp_cafe_settings(vendor_id,preferences) VALUES(:v,CAST(:p AS jsonb))
                ON CONFLICT(vendor_id) DO UPDATE SET preferences=EXCLUDED.preferences,updated_at=now(),
                enabled_since=CASE WHEN :reset THEN now() ELSE whatsapp_cafe_settings.enabled_since END'''),dict(v=vendor_id,p=json.dumps(prefs),reset=reset))
            db.session.commit()
        except (ValueError,TypeError,AttributeError):return jsonify(error='Check reminder minutes, HTTPS link, switches and approved template fields.'),400
    return jsonify(preferences(vendor_id))


@whatsapp_preferences.put('/vendor/<int:vendor_id>/whatsapp/contacts')
@require_vendor_permission('account.manage')
def contact_consent(vendor_id):
    body=request.get_json(silent=True) or {}
    try:
        p=phone(body.get('recipient'));note=body.get('consent_note','')
        if not isinstance(note,str) or not 3<=len(note.strip())<=500:raise ValueError()
        if any(type(body.get(k)) is not bool for k in ('service_consent','marketing_consent')):raise ValueError()
    except (ValueError,TypeError):return jsonify(error='Provide country-code phone, consent choices and a consent record.'),400
    db.session.execute(text('''INSERT INTO whatsapp_contacts(vendor_id,recipient,service_consent,marketing_consent,consent_note)
        VALUES(:v,:p,:s,:m,:n) ON CONFLICT(vendor_id,recipient) DO UPDATE SET service_consent=:s,marketing_consent=:m,consent_note=:n,updated_at=now()'''),
        dict(v=vendor_id,p=p,s=body['service_consent'],m=body['marketing_consent'],n=note.strip()))
    db.session.commit()
    return jsonify(saved=True)
