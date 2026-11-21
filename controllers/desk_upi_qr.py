"""Routes for desk UPI QR collection into HFG's Razorpay account."""
import hashlib
import hmac
import os

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import text

from db.extensions import db
from services import desk_upi_qr as qr
from services.vendor_access import require_vendor_permission

desk_upi_qr = Blueprint('desk_upi_qr', __name__)


@desk_upi_qr.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def _actor():
    claims = getattr(g, 'vendor_claims', None) or {}
    staff = claims.get('staff') if isinstance(claims.get('staff'), dict) else {}
    return {
        'source_channel': 'dashboard',
        'staff_id': str(staff.get('id') or staff.get('staff_id') or '') or None,
        'staff_name': staff.get('name'),
        'staff_role': staff.get('role'),
    }


def _emit(vendor_id, state):
    socketio = current_app.extensions.get('socketio')
    if not socketio:
        return
    payload = {
        'vendorId': int(vendor_id), 'bookingId': int(state['booking_id']), 'event': 'upi_qr_' + state['status'],
        'collection_id': state['collection_id'], 'payment_use_case': qr.PAYMENT_USE_CASE,
        'settlement_status': 'completed' if state['status'] == 'paid' else state['status'],
        'cafe_settlement_status': state['cafe_settlement_status'],
    }
    try:
        socketio.emit('booking_payment_update', payload, to=f'vendor_{int(vendor_id)}')
    except TypeError:
        socketio.emit('booking_payment_update', payload, room=f'vendor_{int(vendor_id)}')
    except Exception:
        current_app.logger.warning('desk_upi_qr: socket emit failed for booking %s', state['booking_id'])


def _fail(error):
    db.session.rollback()
    if isinstance(error, qr.QrError):
        return jsonify(success=False, error=str(error)), error.status
    current_app.logger.exception('desk_upi_qr failed')
    return jsonify(success=False, error='Could not reach the payment QR service. Try again.'), 500


@desk_upi_qr.post('/vendor/<int:vendor_id>/bookings/<int:booking_id>/upi-qr')
@require_vendor_permission('booking.manage')
def create(vendor_id, booking_id):
    body = request.get_json(silent=True) or {}
    try:
        state = qr.create_qr(vendor_id, booking_id, body.get('booking_types'), body.get('waive_off_amount') or 0, _actor(),
                             body.get('booking_ids'))
        return jsonify(success=True, **state), 201
    except Exception as error:
        return _fail(error)


@desk_upi_qr.get('/vendor/<int:vendor_id>/upi-qr/<collection_id>')
@require_vendor_permission('booking.manage')
def status(vendor_id, collection_id):
    try:
        before = qr._get(collection_id, vendor_id)['status']
        state = qr.refresh(collection_id, vendor_id)
        if state['status'] != before:
            _emit(vendor_id, state)
        return jsonify(success=True, **state)
    except Exception as error:
        return _fail(error)


@desk_upi_qr.post('/vendor/<int:vendor_id>/upi-qr/<collection_id>/cancel')
@require_vendor_permission('booking.manage')
def cancel(vendor_id, collection_id):
    try:
        state = qr.cancel(collection_id, vendor_id)
        if state['status'] == 'paid':
            _emit(vendor_id, state)
        return jsonify(success=True, **state)
    except Exception as error:
        return _fail(error)


@desk_upi_qr.post('/payments/desk-upi-webhook')
def webhook():
    secret = current_app.config.get('DESK_UPI_WEBHOOK_SECRET') or os.getenv('DESK_UPI_WEBHOOK_SECRET', '')
    expected = hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(expected, request.headers.get('X-Razorpay-Signature', '')):
        return '', 403
    body = request.get_json(silent=True) or {}
    if body.get('event') != 'qr_code.credited':
        return '', 200
    payload = body.get('payload') or {}
    qr_entity = (payload.get('qr_code') or {}).get('entity') or {}
    payment = (payload.get('payment') or {}).get('entity') or {}
    collection_id = qr.collection_for_qr(qr_entity.get('id'))
    if not collection_id:
        return '', 200  # Another product on the shared HFG account.
    try:
        state, changed = qr.apply_payment(collection_id, payment)
        if changed:
            vendor_id = db.session.execute(text('SELECT vendor_id FROM desk_upi_collections WHERE id=:id'),
                                           {'id': collection_id}).scalar()
            _emit(vendor_id, state)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('desk_upi_qr webhook failed for %s', qr_entity.get('id'))
        return '', 503  # Razorpay retries.
    return '', 200
