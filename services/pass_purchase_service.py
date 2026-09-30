"""Authenticated, atomic pass purchase. Caller commits before responding."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import razorpay
from flask import current_app
from db.extensions import db
from models.user import User
from models.passModels import CafePass, UserPass
from models.passPurchase import PassPurchase
from models.bookingGatewayPayment import BookingGatewayPayment
from models.transaction import Transaction
from services.pass_service import PassService, IST


class PurchaseError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def purchase(user_id, body):
    if not isinstance(body, dict):
        raise PurchaseError('A JSON object is required')
    if body.get('user_id') is not None and str(body['user_id']) != str(user_id):
        raise PurchaseError('Cannot purchase a pass for another user', 403)
    pass_id = body.get('cafe_pass_id')
    if type(pass_id) is not int or pass_id <= 0:
        raise PurchaseError('cafe_pass_id must be a positive integer')
    mode = str(body.get('payment_mode', 'payment_gateway')).strip().lower()
    mode = {'hash_wallet': 'wallet', 'gateway': 'payment_gateway'}.get(mode, mode)
    if mode not in ('wallet', 'payment_gateway'):
        raise PurchaseError('Pass purchases support Hash Wallet or payment gateway only')
    payment_id = body.get('payment_id')
    key = body.get('idempotency_key') or (payment_id if mode == 'payment_gateway' else None)
    if not isinstance(key, str) or not 8 <= len(key) <= 100:
        raise PurchaseError('Supply an idempotency_key of 8–100 characters')
    fingerprint = hashlib.sha256(json.dumps([pass_id, mode, payment_id], sort_keys=True).encode()).hexdigest()
    # Serializes same-user retries, including first-time purchases.
    user = User.query.filter_by(id=user_id).populate_existing().with_for_update().first()
    if not user or getattr(user, 'deleted_at', None):
        raise PurchaseError('User not found', 404)
    previous = PassPurchase.query.filter_by(user_id=user_id, idempotency_key=key).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise PurchaseError('Idempotency key already used for another purchase', 409)
        return db.session.get(UserPass, previous.user_pass_id), previous.transaction_id, True
    catalog = db.session.get(CafePass, pass_id)
    if not catalog or not catalog.is_active:
        raise PurchaseError('Pass not available', 404)
    catalog.validate()
    if catalog.vendor_id is not None:
        from services.payment_methods import require_method
        require_method(catalog.vendor_id, 'cafe_specific_pass')
        require_method(catalog.vendor_id, 'hash_wallet' if mode == 'wallet' else 'payment_gateway')
    price = Decimal(str(catalog.price))
    if not price.is_finite() or price <= 0 or price * 100 != (price * 100).to_integral_value():
        raise PurchaseError('Invalid pass price')
    if mode == 'payment_gateway':
        if not isinstance(payment_id, str) or not payment_id:
            raise PurchaseError('payment_id is required')
        gateway = razorpay.Client(auth=(current_app.config.get('RAZORPAY_KEY_ID'), current_app.config.get('RAZORPAY_KEY_SECRET')))
        try:
            payment = gateway.payment.fetch(payment_id)
            order = gateway.order.fetch(payment.get('order_id'))
        except Exception:
            raise PurchaseError('Unable to verify payment', 502)
        notes = order.get('notes') or {}
        if str(notes.get('user_id')) != str(user_id) or str(notes.get('cafe_pass_id')) != str(pass_id):
            raise PurchaseError('Payment order does not belong to this user and pass', 403)
        if payment.get('status') != 'captured' or payment.get('currency') != 'INR' or payment.get('amount') != int(price * 100):
            raise PurchaseError('Captured INR payment must match the pass price')
        # Shared with booking confirmation: payment/order cannot buy both a pass and a booking.
        if BookingGatewayPayment.query.filter_by(payment_id=payment_id).first():
            raise PurchaseError('Payment already used', 409)
        db.session.add(BookingGatewayPayment(payment_id=payment_id, order_id=str(payment['order_id']),
            user_id=user_id, amount=price, currency='INR', status='pass_purchase'))
        db.session.flush()
    else:
        from services.booking_service import BookingService
        BookingService.debit_wallet(user_id, 'pass:' + hashlib.sha256(key.encode()).hexdigest()[:40], price)
    if catalog.pass_mode == 'hour_based':
        owned = PassService.create_hour_based_pass(user_id, pass_id)
    else:
        today = datetime.now(IST).date()
        owned = UserPass(user_id=user_id, cafe_pass_id=pass_id, pass_mode='date_based',
            valid_from=today, valid_to=today + timedelta(days=catalog.days_valid), is_active=True,
            purchased_at=datetime.utcnow())
        db.session.add(owned)
        db.session.flush()
    transaction = Transaction(user_id=user_id, vendor_id=catalog.vendor_id, user_name=user.name or 'Gamer',
        original_amount=float(price), discounted_amount=0, amount=float(price), mode_of_payment=mode,
        payment_use_case='hash_wallet' if mode == 'wallet' else 'payment_gateway',
        booking_type='pass_purchase', settlement_status='completed', source_channel='app',
        reference_id=payment_id if mode == 'payment_gateway' else 'pass:' + str(owned.id))
    db.session.add(transaction)
    db.session.flush()
    db.session.add(PassPurchase(user_id=user_id, idempotency_key=key, fingerprint=fingerprint,
        user_pass_id=owned.id, transaction_id=transaction.id))
    return owned, transaction.id, False
