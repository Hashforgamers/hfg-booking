# models/voucher.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from datetime import datetime
from db.extensions import db

class Voucher(db.Model):
    __tablename__ = 'vouchers'

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    discount_percentage = Column(Integer, default=100)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="vouchers")

    def __repr__(self):
        return f"<Voucher code={self.code} user_id={self.user_id} active={self.is_active}>"
