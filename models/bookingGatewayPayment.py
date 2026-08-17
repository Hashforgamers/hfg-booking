from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String

from db.extensions import db


class BookingGatewayPayment(db.Model):
    """One consumed Razorpay payment for one booking-confirmation batch."""

    __tablename__ = "booking_gateway_payments"

    id = Column(Integer, primary_key=True)
    payment_id = Column(String(120), nullable=False, unique=True, index=True)
    order_id = Column(String(120), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    status = Column(String(32), nullable=False, default="processing", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
