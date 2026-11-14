"""Compatibility for shipped Flutter pass checkout; issuance still requires authentication.

The old app creates an anonymous amount-only order, then submits the signed
checkout result with its bearer token. Only that verified result may bind the
payment to a user. A payment ID alone is never ownership evidence.
"""
from functools import wraps
import re
from decimal import Decimal
from flask import request

LEGACY_PASS_VERSION = 'flutter_pass_v1'


def is_legacy_pass_request(body):
    return (isinstance(body, dict)
            and set(body) == {'amount', 'currency', 'receipt'}
            and body.get('currency') == 'INR'
            and isinstance(body.get('receipt'), str)
            and re.fullmatch(r'pass_rcpt_\d{10,16}', body['receipt']) is not None)


def is_legacy_pass_order(order):
    notes = order.get('notes') or {}
    return (notes.get('source') == 'hfg_booking'
            and notes.get('purpose') == 'game_pass'
            and notes.get('checkout_version') == LEGACY_PASS_VERSION)


def pass_order_auth(fn):
    from services.security import auth_required_self
    authenticated = auth_required_self(decrypt_user=True)(fn)

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not request.headers.get('Authorization') and is_legacy_pass_request(request.get_json(silent=True)):
            return fn(*args, **kwargs)
        return authenticated(*args, **kwargs)
    return wrapper


def claim_legacy_payment(user_id, payment, order_id):
    """Called only AFTER HMAC, gateway order linkage and captured status checks."""
    from db.extensions import db
    from models.bookingGatewayPayment import BookingGatewayPayment
    from sqlalchemy import or_
    from sqlalchemy.exc import IntegrityError
    if payment.get('status') != 'captured' or payment.get('currency') != 'INR':
        raise ValueError('A captured INR payment is required')
    payment_id = payment.get('id')
    if not payment_id or not order_id:
        raise ValueError('Missing verified payment identifiers')
    amount = Decimal(str(payment.get('amount'))) / 100
    if not amount.is_finite() or amount <= 0:
        raise ValueError('Invalid payment amount')
    existing = BookingGatewayPayment.query.filter(or_(
        BookingGatewayPayment.payment_id == payment_id,
        BookingGatewayPayment.order_id == order_id,
    )).with_for_update().first()
    if existing:
        if (existing.user_id != user_id or existing.payment_id != payment_id
                or existing.order_id != order_id or existing.status not in ('pass_checkout', 'pass_purchase')):
            raise ValueError('Payment already claimed or used')
        db.session.commit()
        return
    db.session.add(BookingGatewayPayment(payment_id=payment_id, order_id=order_id,
        user_id=user_id, amount=amount, currency='INR', status='pass_checkout'))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError('Payment already claimed; retry the same checkout')
