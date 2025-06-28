# models/voucher_redemption_log.py
from sqlalchemy import Column, Integer, ForeignKey, DateTime
from datetime import datetime
from db.extensions import db

class VoucherRedemptionLog(db.Model):
    __tablename__ = 'voucher_redemption_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    voucher_id = Column(Integer, ForeignKey('vouchers.id'), nullable=False)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=True)
    redeemed_at = Column(DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="voucher_redemptions")
    voucher = db.relationship("Voucher", backref="redemption_logs")
