"""Short-lived gamer checkout identity, using existing Hash auth or email OTP."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid
import jwt
from flask import Blueprint, current_app, g, jsonify, request
from flask_mail import Message
from sqlalchemy import text
from db.extensions import db, mail
from services.security import auth_required_self

cafe_checkout_blueprint = Blueprint('cafe_checkout', __name__)


def issue_token(user_id):
    now = datetime.now(timezone.utc)
    token = jwt.encode({'sub': str(user_id), 'scope': 'cafe_gamer',
        'aud': 'cafe-checkout', 'iat': now, 'exp': now + timedelta(minutes=30)},
        current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return jsonify(token=token, expires_in=1800)


@cafe_checkout_blueprint.post('/cafe-checkout/token')
@auth_required_self(decrypt_user=True)
def cafe_checkout_token():
    if getattr(g, 'token_expired', False):
        return jsonify(error='Sign in again'), 401
    return issue_token(g.auth_user_id)


def digest(value):
    return hmac.new(current_app.config['JWT_SECRET_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()


@cafe_checkout_blueprint.post('/cafe-checkout/login/request')
def request_login():
    body = request.get_json(silent=True) or {}
    email = str(body.get('email') or '').strip().lower()
    if not 3 < len(email) <= 254 or '@' not in email:
        return jsonify(error='Enter a valid email address'), 400
    email_hash, ip_hash = digest(email), digest(request.remote_addr or '')
    # Database lock makes rate limits effective across processes.
    db.session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key':'cafe-login:'+ip_hash})
    db.session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key':'cafe-login:'+email_hash})
    count = db.session.execute(text("SELECT COUNT(*) FROM cafe_login_challenges WHERE created_at > NOW() - INTERVAL '15 minutes' AND (email_hash=:email OR ip_hash=:ip)"), {'email':email_hash,'ip':ip_hash}).scalar()
    if count >= 5:
        db.session.rollback()
        return jsonify(error='Too many attempts. Try again in 15 minutes.'), 429
    row = db.session.execute(text("SELECT u.id FROM users u JOIN contact_info c ON c.parent_id=u.id AND c.parent_type='user' WHERE lower(c.email)=:email AND (to_jsonb(u)->>'deleted_at') IS NULL ORDER BY u.id LIMIT 1"), {'email':email}).first()
    challenge_id, code = str(uuid.uuid4()), f'{secrets.randbelow(1000000):06d}'
    db.session.execute(text('''INSERT INTO cafe_login_challenges
        (id,user_id,email_hash,ip_hash,code_hash,attempts,created_at,expires_at)
        VALUES (:id,:uid,:email,:ip,:code,0,NOW(),NOW()+INTERVAL '10 minutes')'''),
        {'id':challenge_id,'uid':row[0] if row else None,'email':email_hash,'ip':ip_hash,'code':digest(challenge_id+code)})
    db.session.commit()
    if row:
        try:
            mail.send(Message(subject='Your Hash cafe sign-in code', recipients=[email],
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                body=f'Your Hash sign-in code is {code}. It expires in 10 minutes. Do not share this code.'))
        except Exception:
            current_app.logger.exception('Cafe sign-in email delivery failed')
            return jsonify(error='Unable to send a code right now. Try again later.'), 503
    return jsonify(challenge_id=challenge_id, message='If this email belongs to a Hash gamer, a code has been sent.')


@cafe_checkout_blueprint.post('/cafe-checkout/login/verify')
def verify_login():
    body = request.get_json(silent=True) or {}
    challenge_id, code = str(body.get('challenge_id') or ''), str(body.get('code') or '')
    row = db.session.execute(text('SELECT * FROM cafe_login_challenges WHERE id=:id FOR UPDATE'), {'id':challenge_id}).mappings().first()
    if not row or row['consumed_at'] or row['attempts'] >= 5 or row['expires_at'] <= datetime.utcnow():
        db.session.rollback()
        return jsonify(error='Code is invalid or expired'), 401
    db.session.execute(text('UPDATE cafe_login_challenges SET attempts=attempts+1 WHERE id=:id'), {'id':challenge_id})
    if not row['user_id'] or not hmac.compare_digest(row['code_hash'], digest(challenge_id+code)):
        db.session.commit()
        return jsonify(error='Code is invalid or expired'), 401
    db.session.execute(text('UPDATE cafe_login_challenges SET consumed_at=NOW() WHERE id=:id'), {'id':challenge_id})
    db.session.commit()
    return issue_token(row['user_id'])
