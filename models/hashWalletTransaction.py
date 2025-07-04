# models/hash_wallet_transaction.py
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime
from db.extensions import db

class HashWalletTransaction(db.Model):
    __tablename__ = 'hash_wallet_transactions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Integer, nullable=False)  # +ve for credit, -ve for debit
    type = Column(String(50))  # e.g., 'booking', 'top-up', 'admin-credit', etc.
    reference_id = Column(Integer, nullable=True)  # Booking ID or other context
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<HashWalletTransaction user_id={self.user_id} amount={self.amount} type={self.type}>"
