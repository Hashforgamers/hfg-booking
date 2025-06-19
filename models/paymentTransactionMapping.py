# models/payment_transaction_mapping.py
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from db.extensions import db

class PaymentTransactionMapping(db.Model):
    __tablename__ = 'payment_transaction_mappings'

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=False)
    transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    payment_id = Column(String(100), nullable=False)

    # Relationships (optional but helpful)
    booking = db.relationship('Booking', backref='payment_mapping', uselist=False)
    transaction = db.relationship('Transaction', backref='payment_mapping', uselist=False)

    # Prevent duplicate mapping for same booking or transaction
    __table_args__ = (
        UniqueConstraint('booking_id', name='uix_booking_id'),
        UniqueConstraint('transaction_id', name='uix_transaction_id'),
    )

    def __repr__(self):
        return f"<PaymentTransactionMapping booking_id={self.booking_id} transaction_id={self.transaction_id} payment_id={self.payment_id}>"
