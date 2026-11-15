"""Read-only provider diagnostics and business reporting for HFG operations."""
import json
from datetime import datetime,timedelta,timezone
from decimal import Decimal, InvalidOperation
import requests
from flask import Blueprint,jsonify,request,current_app
from sqlalchemy import text
from db.extensions import db
from services.whatsapp import settings,templates
from controllers.whatsapp_payments import admin

operations=Blueprint('whatsapp_operations',__name__)


@operations.after_request
def no_cache(response):
    response.headers['Cache-Control']='no-store'
    return response


def meta_get(c,path,params=None):
    response=requests.get(f"https://graph.facebook.com/{c['API_VERSION']}/{path}",
        headers={'Authorization':'Bearer '+c['ACCESS_TOKEN']},params=params,timeout=15)
    if not response.ok:
        try:error=response.json().get('error',{})
        except (ValueError,AttributeError):error={}
        message=str(error.get('message') or 'Meta rejected the request.')
        for secret in (c.get('ACCESS_TOKEN'),c.get('APP_SECRET'),c.get('VERIFY_TOKEN')):
            if secret:message=message.replace(secret,'[redacted]')
        code=error.get('code')
        subcode=error.get('error_subcode')
        reference=f"HTTP {response.status_code}"+(f", Meta code {code}" if code is not None else '')+(f", subcode {subcode}" if subcode is not None else '')
        raise ValueError(f'{reference}: {message}')
    return response.json()


def period():
    try:days=int(request.args.get('days','30'))
    except ValueError:raise ValueError('Choose 7, 30 or 90 days.')
    if days not in (7,30,90):raise ValueError('Choose 7, 30 or 90 days.')
    end=datetime.now(timezone.utc)
    return days,end-timedelta(days=days),end


@operations.get('/admin/whatsapp/operations')
@admin
def business_report():
    try:days,start,end=period()
    except ValueError as error:return jsonify(error=str(error)),400
    purchases=db.session.execute(text("SELECT count(*) AS packs,COALESCE(sum(amount_paise),0) AS revenue_paise FROM whatsapp_purchases WHERE status='paid' AND paid_at>=:start AND paid_at<:end"),dict(start=start,end=end)).mappings().one()
    statuses=db.session.execute(text('SELECT status,count(*) AS count FROM whatsapp_outbox WHERE created_at>=:start AND created_at<:end GROUP BY status'),dict(start=start,end=end)).mappings().all()
    credits=db.session.execute(text('SELECT COALESCE(sum(credits),0) AS balance,count(*) FILTER(WHERE credits>0) AS active_cafes FROM whatsapp_wallet')).mappings().one()
    checks=db.session.execute(text('SELECT name,observed_at FROM whatsapp_provider_checks')).mappings().all()
    config_date=db.session.execute(text('SELECT updated_at FROM whatsapp_config WHERE id=1')).scalar()
    cafes=db.session.execute(text('''SELECT w.vendor_id,v.cafe_name,w.credits,
        COALESCE(p.packs,0) AS packs,COALESCE(p.revenue_paise,0) AS revenue_paise
        FROM whatsapp_wallet w JOIN vendors v ON v.id=w.vendor_id
        LEFT JOIN (SELECT vendor_id,count(*) AS packs,sum(amount_paise) AS revenue_paise FROM whatsapp_purchases
        WHERE status='paid' AND paid_at>=:start AND paid_at<:end GROUP BY vendor_id) p ON p.vendor_id=w.vendor_id
        ORDER BY revenue_paise DESC,v.cafe_name'''),dict(start=start,end=end)).mappings().all()
    base=request.url_root.rstrip('/')
    return jsonify(webhook_urls={'meta':base+'/api/whatsapp/webhook','razorpay':base+'/api/whatsapp/payment-webhook'},days=days,start=start.isoformat(),end=end.isoformat(),currency='INR',purchases=dict(purchases),credits=dict(credits),
        statuses=[dict(r) for r in statuses],cafes=[dict(r) for r in cafes],
        webhook_checks=[dict(name=r['name'],observed_at=r['observed_at'].isoformat(),current=not config_date or r['observed_at']>=config_date) for r in checks])


@operations.post('/admin/whatsapp/validate')
@admin
def validate_connections():
    c=settings();results=[]
    def check(name,fn):
        try:results.append(dict(name=name,status='passed',detail=fn()))
        except ValueError as error:
            results.append(dict(name=name,status='failed',detail=str(error)))
        except (KeyError,requests.RequestException):
            results.append(dict(name=name,status='failed',detail='Could not verify. Check saved credentials, IDs, permissions and provider availability.'))
    if all(c.get(k) for k in ('PHONE_NUMBER_ID','ACCESS_TOKEN','API_VERSION')):
        def sender():
            row=meta_get(c,c['PHONE_NUMBER_ID'],{'fields':'id,verified_name,display_phone_number,quality_rating'})
            if str(row.get('id'))!=c['PHONE_NUMBER_ID']:raise ValueError('Meta returned a different phone number ID. Check the saved ID.')
            return f"{row.get('verified_name','Sender')} · {row.get('display_phone_number','')} · quality {row.get('quality_rating','not reported')}"
        check('Meta sender',sender)
    else:results.append(dict(name='Meta sender',status='missing',detail='Save the phone number ID, access token and API version first.'))
    if c.get('WABA_ID') and c.get('ACCESS_TOKEN'):
        def account():
            row=meta_get(c,c['WABA_ID'],{'fields':'id,name,currency'})
            phones=meta_get(c,c['WABA_ID']+'/phone_numbers',{'fields':'id','limit':100})
            if not any(str(p.get('id'))==c.get('PHONE_NUMBER_ID') for p in phones.get('data',[])):raise ValueError('The configured phone number ID is not listed under this WABA. Check that both IDs belong to the same WhatsApp account.')
            return f"{row.get('name','WhatsApp account')} · currency {row.get('currency','not reported')} · sender belongs to this account"
        check('Meta account and sender ownership',account)
        saved_templates=templates()
        if saved_templates:
            def approved_templates():
                found={}
                cursor=None
                for _ in range(10):
                    params={'fields':'name,language,status','limit':100}
                    if cursor:params['after']=cursor
                    page=meta_get(c,c['WABA_ID']+'/message_templates',params)
                    for row in page.get('data',[]):found[(row['name'],row['language'])]=row.get('status')
                    if not page.get('paging',{}).get('next'):break
                    cursor=page['paging']['cursors']['after']
                missing=[t['name'] for t in saved_templates if found.get((t['name'],t['language']))!='APPROVED']
                if missing:raise ValueError('These configured templates are missing or not approved in Meta: '+', '.join(missing)+'.')
                return f'All {len(saved_templates)} configured templates are approved in Meta.'
            check('Template approval',approved_templates)
        else:results.append(dict(name='Template approval',status='missing',detail='No templates are configured. Add at least one Meta-approved template before sending.'))
    else:results.append(dict(name='Meta account and templates',status='missing',detail='Save the WhatsApp Business Account ID (WABA ID).'))
    key=current_app.config.get('RAZORPAY_KEY_ID');secret=current_app.config.get('RAZORPAY_KEY_SECRET')
    if key and secret:
        def payment():
            response=requests.get('https://api.razorpay.com/v1/orders',auth=(key,secret),params={'count':1},timeout=15)
            if not response.ok:raise ValueError(f'Razorpay rejected the read-only API request (HTTP {response.status_code}). Check that the server key ID and key secret match the account mode.')
            mode='TEST' if key.startswith('rzp_test_') else 'LIVE' if key.startswith('rzp_live_') else 'unknown mode'
            return f'Credentials accepted · {mode}. Read-only check; no payment created or charged.'
        check('Razorpay API',payment)
    else:results.append(dict(name='Razorpay API',status='missing',detail='Configure RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET on the booking server.'))
    webhook_evidence={row['name']:row['observed_at'] for row in db.session.execute(
        text('SELECT name,observed_at FROM whatsapp_provider_checks WHERE name IN (:meta_signed,:meta_verify,:razorpay_signed)'),
        {'meta_signed':'meta_signed_callback','meta_verify':'meta_verification','razorpay_signed':'razorpay_signed_callback'}
    ).mappings()}
    saved_at=db.session.execute(text('SELECT updated_at FROM whatsapp_config WHERE id=1')).scalar()
    for name,key,evidence_key in [
        ('Meta signed webhook','APP_SECRET','meta_signed_callback'),
        ('Meta verification token','VERIFY_TOKEN','meta_verification'),
        ('Razorpay signed webhook','PAYMENT_WEBHOOK_SECRET','razorpay_signed_callback'),
    ]:
        observed_at=webhook_evidence.get(evidence_key)
        current=observed_at is not None and (saved_at is None or observed_at>=saved_at)
        if not c.get(key):
            status,detail='missing','Save the required secret first.'
        elif current:
            status,detail='passed',f"A successful provider callback was received at {observed_at.isoformat()}."
        else:
            status,detail='pending','Secret saved. Complete a successful provider callback after the latest settings save; see Webhook evidence below.'
        results.append(dict(name=name,status=status,detail=detail))
    return jsonify(checked_at=datetime.now(timezone.utc).isoformat(),checks=results,
        note='API access checks do not prove delivery, payment capture, or webhook signatures. Complete the provider test steps before enabling live use.')


@operations.get('/admin/whatsapp/meta-report')
@admin
def meta_report():
    try:
        days,start,end=period();c=settings()
        if not all(c.get(k) for k in ('WABA_ID','ACCESS_TOKEN','API_VERSION')):
            return jsonify(error='Save WABA ID, access token and API version before fetching Meta costs.'),400
        account=meta_get(c,c['WABA_ID'],{'fields':'currency'})
        points=[];cursor=None
        for _ in range(20):
            params={'start':int(start.timestamp()),'end':int(end.timestamp()),'granularity':'DAILY',
                    'metric_types':json.dumps(['COST','VOLUME']),'dimensions':json.dumps(['PRICING_CATEGORY'])}
            if cursor:params['after']=cursor
            page=meta_get(c,c['WABA_ID']+'/pricing_analytics',params)
            for group in page.get('data',[]):points.extend(group.get('data_points',[]))
            if not page.get('paging',{}).get('next'):break
            cursor=page['paging']['cursors']['after']
        else:return jsonify(error='Report exceeds this page limit; choose a shorter period.'),422
        rows=[]
        for point in points:
            rows.append({k:point.get(k) for k in ('start','end','pricing_category','volume','cost')})
        cost=sum((Decimal(str(p['cost'])) for p in rows if p.get('cost') is not None),Decimal(0))
        return jsonify(days=days,currency=account.get('currency'),cost=str(cost) if rows and any(p.get('cost') is not None for p in rows) else None,
            scope='Entire WhatsApp Business Account; may include activity outside HFG.',rows=rows,
            fetched_at=datetime.now(timezone.utc).isoformat(),balance=None,
            balance_note='Current billing balance is not provided by this report. Open Meta Billing for the authoritative balance and invoices.')
    except (ValueError,KeyError,TypeError,InvalidOperation,requests.RequestException):
        return jsonify(error='Meta report unavailable. Check account ID, analytics permissions and API version. No zero-cost estimate has been substituted.'),502
