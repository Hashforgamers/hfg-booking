from sqlalchemy import Column, Integer, ForeignKey, String , DateTime
from db.extensions import db
# models/hash_coin_transaction.py
class HashCoinTransaction(db.Model):
    __tablename__ = 'hash_coin_transactions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    coins_changed = Column(Integer, nullable=False)  # +1000 or -10000
    reason = Column(String(255))  # e.g., "Booking", "Voucher Redemption"
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="hash_coin_transactions")
