from sqlalchemy import Column, Integer, Date, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from db.extensions import db

class UserPass(db.Model):
    __tablename__ = 'user_passes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    cafe_pass_id = Column(Integer, ForeignKey('cafe_passes.id'), nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True)
    cafe_pass = relationship('CafePass')
    user = relationship('User')
    # Optionally, add: status, cancel_reason, etc.
