"""Permission checks for staff credit operations, using signed vendor tokens."""
from functools import wraps

import jwt
import time
from sqlalchemy import text
from db.extensions import db
from flask import current_app, jsonify, request, g


def vendor_id_from_claims(claims):
    vendor = claims.get("vendor") or {}
    subject = claims.get("sub") or {}
    value = claims.get("vendor_id")
    if value is None and isinstance(vendor, dict):
        value = vendor.get("id")
    if value is None and isinstance(subject, dict):
        value = subject.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def permits(claims, vendor_id, permissions):
    if vendor_id_from_claims(claims) != vendor_id:
        return False
    if claims.get("scope") == "vendor_access":
        staff = claims.get("staff") or {}
        return bool(set(staff.get("permissions") or []) & set(permissions))
    # Match the dashboard service's signed legacy owner-token support.
    subject = claims.get("sub")
    return claims.get("scope") is None and isinstance(subject, dict) and subject.get("type") == "vendor"


def require_vendor_permission(*permissions):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify(success=False, error="Please sign in again."), 401
            try:
                claims = jwt.decode(
                    auth[7:], current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"],
                    options={"require": ["exp", "iat"], "verify_sub": False},
                )
            except jwt.InvalidTokenError:
                return jsonify(success=False, error="Session expired or invalid. Please sign in again."), 401
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                return jsonify(error='A JSON object is required'), 400
            try:
                vendor_id = int(kwargs.get('vendor_id') or body.get('vendor_id') or body.get('vendorId') or request.args.get('vendor_id') or vendor_id_from_claims(claims))
            except (TypeError, ValueError):
                return jsonify(error='Cafe context is required'), 400
            internal = (claims.get('scope') == 'booking_action'
                and claims.get('vendor_id') == vendor_id
                and claims.get('endpoint') == fn.__name__
                and str(claims.get('booking_id')) == str(body.get('booking_id'))
                and fn.__name__ in {'accept_pay_at_cafe_booking', 'reject_pay_at_cafe_booking'})
            if not internal and not permits(claims, vendor_id, permissions):
                return jsonify(success=False, error="You do not have permission for this credit operation."), 403
            if claims.get('scope') == 'vendor_access':
                active = db.session.execute(text('SELECT 1 FROM cafe_staff_sessions WHERE jti=:jti AND closed_at IS NULL AND expires_at>CURRENT_TIMESTAMP'), {'jti':claims.get('jti')}).first()
                if not active:
                    return jsonify(error='Unlock your staff session again'), 401
            # Resolve target ownership from persisted records, not just the supplied cafe ID.
            ids = body.get('booking_ids') or body.get('booking_id') or kwargs.get('booking_id') or []
            ids = ids if isinstance(ids, list) else [ids]
            try:
                for bid in ids:
                    row = db.session.execute(text('SELECT ag.vendor_id FROM bookings b JOIN available_games ag ON ag.id=b.game_id WHERE b.id=:bid'), {'bid':int(bid)}).first()
                    if row and row[0] != vendor_id:
                        return jsonify(error='Booking belongs to another cafe'), 403
                game = body.get('game_id') or body.get('gameId')
                if game:
                    row = db.session.execute(text('SELECT vendor_id FROM available_games WHERE id=:id'), {'id':int(game)}).first()
                    if row and row[0] != vendor_id:
                        return jsonify(error='Game belongs to another cafe'), 403
            except (TypeError, ValueError):
                return jsonify(error='Invalid booking or game identifier'), 400
            g.vendor_claims = claims
            g.vendor_id = vendor_id
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def internal_booking_headers(vendor_id, booking_id, action):
    now = int(time.time())
    token = jwt.encode({'scope':'booking_action', 'vendor_id':int(vendor_id),
        'booking_id':int(booking_id), 'endpoint':f'{action}_pay_at_cafe_booking',
        'iat':now, 'exp':now+60}, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return {'Authorization':'Bearer '+token}
