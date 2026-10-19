"""Scheduled booking debits/refunds in the cafe's paise wallet, same DB transaction."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from sqlalchemy import text
from db.extensions import db


def paise(value):
    try:
        amount=Decimal(str(value))
        if not amount.is_finite() or amount<0: raise ValueError()
        return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError('Invalid cafe wallet amount')


def move(vendor_id,user_id,booking_id,amount,*,refund=False,component='booking'):
    units=paise(amount)
    if not units:return 0
    if component not in ('booking','controller'):raise ValueError('Invalid wallet component')
    # Shared with QR reservations, extensions and desk topups (vendor before wallet).
    db.session.execute(text('SELECT pg_advisory_xact_lock(220926,:vid)'),{'vid':int(vendor_id)})
    identity=f'booking-{component}:{int(booking_id)}'
    idem=('refund:' if refund else 'debit:')+identity
    fp=hashlib.sha256(f'{vendor_id}:{user_id}:{booking_id}:{units}:{refund}:{component}'.encode()).hexdigest()
    old=db.session.execute(text('SELECT fingerprint FROM cafe_wallet_ledger WHERE vendor_id=:vid AND idempotency_key=:key'),{'vid':vendor_id,'key':idem}).scalar()
    if old:
        if old!=fp:raise ValueError('Cafe wallet idempotency conflict')
        return units
    db.session.execute(text('INSERT INTO cafe_wallets(vendor_id,user_id,balance,reserved) VALUES(:vid,:uid,0,0) ON CONFLICT DO NOTHING'),{'vid':vendor_id,'uid':user_id})
    wallet=db.session.execute(text('SELECT balance,reserved FROM cafe_wallets WHERE vendor_id=:vid AND user_id=:uid FOR UPDATE'),{'vid':vendor_id,'uid':user_id}).first()
    if refund:
        paid=db.session.execute(text('''SELECT SUM(-amount) FROM cafe_wallet_ledger
          WHERE vendor_id=:vid AND user_id=:uid AND idempotency_key IN (:base,:controller)'''),
          {'vid':vendor_id,'uid':user_id,'base':f'debit:booking-booking:{int(booking_id)}','controller':f'debit:booking-controller:{int(booking_id)}'}).scalar()
        if paid is None or units>paid:raise ValueError('Refund exceeds cafe wallet booking debit')
    elif wallet.balance-wallet.reserved<units:
        raise ValueError('Insufficient cafe wallet balance')
    delta=units if refund else -units
    balance=db.session.execute(text('UPDATE cafe_wallets SET balance=balance+:delta WHERE vendor_id=:vid AND user_id=:uid RETURNING balance'),{'delta':delta,'vid':vendor_id,'uid':user_id}).scalar_one()
    db.session.execute(text('''INSERT INTO cafe_wallet_ledger(vendor_id,user_id,kind,amount,balance_after,reserved_after,
      actor_id,actor_name,method,reason,idempotency_key,fingerprint,created_at)
      VALUES(:vid,:uid,:kind,:delta,:balance,:reserved,:actor,'Hash app','cafe_wallet',:reason,:key,:fp,(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))'''),
      {'vid':vendor_id,'uid':user_id,'kind':'booking_refund' if refund else 'booking_debit','delta':delta,
       'balance':balance,'reserved':wallet.reserved,'actor':f'user-{user_id}',
       'reason':f'{"Refund" if refund else "Payment"} for booking #{booking_id} ({component})','key':idem,'fp':fp})
    return units
