# models/hash_wallet.py
from sqlalchemy import Column, Integer, ForeignKey
from db.extensions import db

class HashWallet(db.Model):
    __tablename__ = 'hash_wallets'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    balance = Column(Integer, default=0)

    def __repr__(self):
        return f"<HashWallet user_id={self.user_id} balance={self.balance}>"
