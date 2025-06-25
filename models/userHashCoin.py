# models/user_hash_coin.py
from sqlalchemy import Column, Integer, ForeignKey, DateTime
from datetime import datetime
from db.extensions import db

class UserHashCoin(db.Model):
    __tablename__ = 'user_hash_coins'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    hash_coins = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref="hash_coin_balance")
