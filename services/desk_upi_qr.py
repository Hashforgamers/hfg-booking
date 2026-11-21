"""Desk UPI QR: collect a booking's pending charges into HFG's Razorpay account.

Flow: staff request a QR for the booking's pending rows -> Razorpay single-use,
fixed-amount UPI QR -> the customer pays -> the webhook (or a status poll) applies
the captured payment: the snapshotted rows become paid via ``hash_upi_qr`` and the
cafe's share is recorded as ``cafe_settlement_status='pending'`` until HFG pays out.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import razorpay
from flask import current_app
from sqlalchemy import bindparam, text

from db.extensions import db

QR_LIFETIME = timedelta(minutes=15)
MODE_OF_PAYMENT = 'hash_upi_qr'
PAYMENT_USE_CASE = 'payment_gateway'
PENDING = ('pending', 'unpaid', 'due')
DEFAULT_TYPES = ('extra', 'additional_meals', 'pay_at_cafe')


class QrError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def gateway():
    key = current_app.config.get('RAZORPAY_KEY_ID')
    secret = current_app.config.get('RAZORPAY_KEY_SECRET')
    if not key or not secret:
        raise QrError('Online payments are not configured.', 503)
    return razorpay.Client(auth=(key, secret))


def _line_total(row):
    with_tax = Decimal(str(row['total_with_tax'] or 0))
    return with_tax if with_tax > 0 else Decimal(str(row['amount'] or 0))


def _pending_rows(booking_ids, booking_types, lock=False):
    sql = '''SELECT id, vendor_id, user_id, user_name, amount, total_with_tax, booking_type
             FROM transactions WHERE booking_id = ANY(:b)
             AND lower(booking_type) <> 'settlement_waive_off'
             AND (settlement_status IS NULL OR lower(settlement_status) IN :pending)'''
    params = {'b': list(booking_ids), 'pending': PENDING}
    if booking_types:
        sql += ' AND lower(booking_type) IN :types'
        params['types'] = tuple(booking_types)
    sql += ' ORDER BY id' + (' FOR UPDATE' if lock else '')
    stmt = text(sql).bindparams(bindparam('pending', expanding=True))
    if booking_types:
        stmt = stmt.bindparams(bindparam('types', expanding=True))
    return [dict(r) for r in db.session.execute(stmt, params).mappings()]


def _public(row):
    return {
        'collection_id': str(row['id']),
        'booking_id': row['booking_id'],
        'status': row['status'],
        'amount_paise': row['amount_paise'],
        'image_url': row['image_url'],
        'close_by': row['close_by'].isoformat() if row['close_by'] else None,
        'paid_at': row['paid_at'].isoformat() if row['paid_at'] else None,
        'cafe_settlement_status': row['cafe_settlement_status'],
    }


def _get(collection_id, vendor_id=None, lock=False):
    try:
        cid = str(uuid.UUID(str(collection_id)))
    except (ValueError, TypeError):
        raise QrError('Unknown payment QR.', 404)
    row = db.session.execute(text('SELECT * FROM desk_upi_collections WHERE id=:id' + (' FOR UPDATE' if lock else '')),
                             {'id': cid}).mappings().first()
    if not row or (vendor_id is not None and row['vendor_id'] != vendor_id):
        raise QrError('Unknown payment QR.', 404)
    return dict(row)


def _close_at_provider(qr_id):
    if not qr_id:
        return
    try:
        gateway().qrcode.close(qr_id)
    except Exception:  # Already closed/paid QRs reject closing; the status check settles the truth.
        current_app.logger.warning('desk_upi_qr: could not close QR %s', qr_id)


def create_qr(vendor_id, booking_id, booking_types=None, waive_off_amount=0, actor=None, extra_booking_ids=None):
    """One QR for a booking's pending rows; extra_booking_ids joins a multi-slot desk booking into one bill."""
    actor = actor or {}
    try:
        booking_ids = sorted({int(booking_id), *(int(b) for b in (extra_booking_ids or []))})
    except (TypeError, ValueError):
        raise QrError('Invalid booking.')
    if len(booking_ids) > 50:
        raise QrError('Too many bookings for one QR.')
    types = sorted({str(t).strip().lower() for t in (booking_types or []) if str(t).strip()} - {'settlement_waive_off'})
    try:
        waive = Decimal(str(waive_off_amount or 0)).quantize(Decimal('0.01'))
    except Exception:
        raise QrError('Invalid waive-off amount.')
    if waive < 0:
        raise QrError('Invalid waive-off amount.')

    # Serialise QR creation per booking.
    owners = db.session.execute(text('''SELECT b.id, ag.vendor_id FROM bookings b JOIN available_games ag ON ag.id=b.game_id
                                        WHERE b.id = ANY(:b) ORDER BY b.id FOR UPDATE OF b'''), {'b': booking_ids}).mappings().all()
    if len(owners) != len(booking_ids) or any(o['vendor_id'] != vendor_id for o in owners):
        raise QrError('Booking not found.', 404)

    rows = _pending_rows(booking_ids, types or None)
    total = sum((_line_total(r) for r in rows), Decimal('0'))
    waive = min(waive, total)
    payable = total - waive
    amount_paise = int((payable * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if amount_paise < 100:
        raise QrError('Nothing to collect by QR. Use End session instead.' if amount_paise <= 0
                      else 'UPI QR needs at least ₹1 due.')
    tx_ids = [r['id'] for r in rows]

    existing = db.session.execute(text('''SELECT * FROM desk_upi_collections WHERE booking_id=:b
                                          AND status IN ('creating','open') FOR UPDATE'''), {'b': booking_id}).mappings().first()
    if existing:
        existing = dict(existing)
        fresh = existing['close_by'] - datetime.now(timezone.utc) > timedelta(minutes=2)
        if (existing['status'] == 'open' and fresh and existing['amount_paise'] == amount_paise
                and sorted(existing['transaction_ids']) == tx_ids
                and Decimal(str(existing['waive_off_amount'])) == waive):
            db.session.commit()
            return _public(existing)
        # The bill changed (or the QR is about to expire): check it was not paid, then replace it.
        db.session.commit()
        state = refresh(existing['id'], vendor_id)
        if state['status'] == 'paid':
            raise QrError('This bill was just paid by QR.', 409)
        if state['status'] in ('open', 'creating'):
            _close_at_provider(existing['qr_id'])
            db.session.execute(text("UPDATE desk_upi_collections SET status='closed', updated_at=now() WHERE id=:id AND status IN ('creating','open')"),
                               {'id': existing['id']})
        db.session.commit()
        return create_qr(vendor_id, booking_id, types, waive_off_amount, actor, extra_booking_ids)

    cafe = db.session.execute(text('SELECT cafe_name FROM vendors WHERE id=:v'), {'v': vendor_id}).scalar() or 'Hash cafe'
    cid = str(uuid.uuid4())
    close_by = datetime.now(timezone.utc) + QR_LIFETIME
    # Persist before calling the provider so an uncertain response never duplicates a live QR.
    db.session.execute(text('''INSERT INTO desk_upi_collections(id,vendor_id,booking_id,transaction_ids,waive_off_amount,amount_paise,
                               close_by,source_channel,staff_id,staff_name,staff_role)
                               VALUES(:id,:v,:b,:tx,:w,:a,:c,:src,:sid,:sn,:sr)'''),
                       dict(id=cid, v=vendor_id, b=booking_id, tx=tx_ids, w=waive, a=amount_paise, c=close_by,
                            src=actor.get('source_channel') or 'dashboard', sid=actor.get('staff_id'),
                            sn=actor.get('staff_name'), sr=actor.get('staff_role')))
    db.session.commit()
    try:
        qr = gateway().qrcode.create({
            'type': 'upi_qr', 'name': str(cafe)[:40], 'usage': 'single_use', 'fixed_amount': True,
            'payment_amount': amount_paise, 'description': f'Booking #{booking_id}'[:255],
            'close_by': int(close_by.timestamp()),
            'notes': {'purpose': 'desk_upi_qr', 'collection_id': cid,
                      'booking_id': str(booking_id), 'vendor_id': str(vendor_id)},
        })
    except Exception as error:
        db.session.rollback()
        db.session.execute(text("UPDATE desk_upi_collections SET status='failed', error=:e, updated_at=now() WHERE id=:id"),
                           {'id': cid, 'e': str(error)[:500]})
        db.session.commit()
        if isinstance(error, QrError):
            raise
        raise QrError('Could not create the payment QR. Try again or collect another way.', 502)
    db.session.execute(text("UPDATE desk_upi_collections SET qr_id=:q, image_url=:img, status='open', updated_at=now() WHERE id=:id"),
                       {'id': cid, 'q': qr['id'], 'img': qr.get('image_url')})
    db.session.commit()
    return _public(_get(cid))


def apply_payment(collection_id, payment):
    """Idempotently mark the snapshotted rows paid. Returns the collection's public state."""
    row = _get(collection_id, lock=True)
    if row['status'] in ('paid', 'paid_unapplied'):
        db.session.commit()
        return _public(row), False
    ok = (payment.get('status') == 'captured' and int(payment.get('amount') or 0) == row['amount_paise']
          and str(payment.get('currency') or 'INR').upper() == 'INR' and payment.get('id'))
    if not ok:
        db.session.commit()
        return _public(row), False

    tx = [dict(r) for r in db.session.execute(text('''SELECT id, vendor_id, user_id, user_name, amount, total_with_tax, settlement_status
                                                     FROM transactions WHERE id = ANY(:ids) ORDER BY id FOR UPDATE'''),
                                               {'ids': list(row['transaction_ids'])}).mappings()]
    still_pending = len(tx) == len(row['transaction_ids']) and all(
        (r['settlement_status'] or 'pending').lower() in PENDING for r in tx)
    if not still_pending:
        # Money arrived but the bill was settled another way meanwhile: HFG must refund or reconcile.
        db.session.execute(text('''UPDATE desk_upi_collections SET status='paid_unapplied', cafe_settlement_status='review',
                                   payment_id=:p, paid_at=now(), updated_at=now(), error='Bill was settled before the QR payment arrived'
                                   WHERE id=:id'''), {'id': row['id'], 'p': payment['id']})
        db.session.commit()
        current_app.logger.error('desk_upi_qr: payment %s for collection %s needs review', payment['id'], row['id'])
        return _public(_get(row['id'])), True

    db.session.execute(text('''UPDATE transactions SET mode_of_payment=:m, payment_use_case=:u, settlement_status='completed',
                               source_channel=:src, initiated_by_staff_id=:sid, initiated_by_staff_name=:sn,
                               initiated_by_staff_role=:sr, updated_at=now() WHERE id = ANY(:ids)'''),
                       dict(m=MODE_OF_PAYMENT, u=PAYMENT_USE_CASE, src=row['source_channel'], sid=row['staff_id'],
                            sn=row['staff_name'], sr=row['staff_role'], ids=list(row['transaction_ids'])))
    waive = float(row['waive_off_amount'] or 0)
    if waive > 0 and tx:
        first = tx[0]
        today = datetime.utcnow()
        # Same auditable negative row the manual desk settlement writes.
        db.session.execute(text('''INSERT INTO transactions(booking_id,vendor_id,user_id,booked_date,booking_date,booking_time,user_name,
            original_amount,discounted_amount,amount,mode_of_payment,payment_use_case,booking_type,settlement_status,source_channel,
            initiated_by_staff_id,initiated_by_staff_name,initiated_by_staff_role,base_amount,meals_amount,controller_amount,
            waive_off_amount,app_fee_amount,taxable_amount,gst_rate,cgst_amount,sgst_amount,igst_amount,total_with_tax,reference_id,
            created_at,updated_at)
            VALUES(:b,:v,:u,:d,:d,:t,:n,:w,:w,-:w,:m,:uc,'settlement_waive_off','completed',:src,:sid,:sn,:sr,0,0,0,:w,0,0,0,0,0,0,-:w,:ref,now(),now())'''),
            dict(b=row['booking_id'], v=first['vendor_id'], u=first['user_id'], d=today.date(), t=today.time(),
                 n=first['user_name'] or 'Unknown User', w=waive, m=MODE_OF_PAYMENT, uc=PAYMENT_USE_CASE,
                 src=row['source_channel'], sid=row['staff_id'], sn=row['staff_name'], sr=row['staff_role'],
                 ref=f"upiqr-{str(row['id'])[:36]}"))
    db.session.execute(text('''UPDATE desk_upi_collections SET status='paid', payment_id=:p, paid_at=now(),
                               cafe_settlement_status='pending', updated_at=now() WHERE id=:id'''),
                       {'id': row['id'], 'p': payment['id']})
    db.session.commit()
    return _public(_get(row['id'])), True


def refresh(collection_id, vendor_id=None):
    """Status check that also asks Razorpay, so the flow works even if a webhook is late."""
    row = _get(collection_id, vendor_id)
    if row['status'] not in ('open', 'creating') or not row['qr_id']:
        return _public(row)
    try:
        payments = gateway().qrcode.fetch_all_payments(row['qr_id']).get('items', [])
    except Exception:
        current_app.logger.warning('desk_upi_qr: payment lookup failed for %s', row['qr_id'])
        payments = []
    for payment in payments:
        if payment.get('status') == 'captured':
            state, _ = apply_payment(row['id'], payment)
            if state['status'] != 'open':
                return state
    if row['close_by'] <= datetime.now(timezone.utc):
        db.session.execute(text("UPDATE desk_upi_collections SET status='expired', updated_at=now() WHERE id=:id AND status='open'"),
                           {'id': row['id']})
        db.session.commit()
        return _public(_get(row['id']))
    return _public(row)


def cancel(collection_id, vendor_id):
    state = refresh(collection_id, vendor_id)
    if state['status'] != 'open':
        return state
    row = _get(collection_id, vendor_id)
    _close_at_provider(row['qr_id'])
    # A payment may land between the check and the close; look once more before closing locally.
    state = refresh(collection_id, vendor_id)
    if state['status'] != 'open':
        return state
    db.session.execute(text("UPDATE desk_upi_collections SET status='closed', updated_at=now() WHERE id=:id AND status='open'"),
                       {'id': row['id']})
    db.session.commit()
    return _public(_get(row['id']))


def collection_for_qr(qr_id):
    return db.session.execute(text('SELECT id FROM desk_upi_collections WHERE qr_id=:q'), {'q': qr_id}).scalar()
