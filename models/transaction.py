from sqlalchemy import Column, Integer, ForeignKey, String, Float, Date, Time, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from db.extensions import db

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=True)  # made nullable
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=True)    # nullable for system-wide transactions
    user_id = Column(Integer, nullable=False)
    booked_date = Column(Date, default=datetime.utcnow().date(), nullable=False)
    booking_date = Column(Date, default=datetime.utcnow().date(), nullable=False)
    booking_time = Column(Time, default=datetime.utcnow().time(), nullable=False)
    user_name = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)
    original_amount = Column(Float, nullable=False)
    discounted_amount = Column(Float, nullable=False, default=0)
    mode_of_payment = Column(String(50), default='online', nullable=False)
    booking_type = Column(String(100), default='booking', nullable=False)  
    settlement_status = Column(String(50), default='pending', nullable=False)

    # Optional: generic reference ID to link to related entities (e.g., pass purchase)
    reference_id = Column(String(100), nullable=True)

    # Timestamps for auditing
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    booking = relationship('Booking', back_populates='transaction')
    vendor = relationship('Vendor', back_populates='transactions')

    def __repr__(self):
        return f"<Transaction user={self.user_name} amount={self.amount} status={self.settlement_status}>"
