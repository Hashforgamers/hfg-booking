from sqlalchemy import Column, Integer, String, Boolean
from app.extension.extensions import db

class PassType(db.Model):
    __tablename__ = 'pass_types'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)  # e.g., "daily", "monthly", "yearly"
    description = Column(String(255))
    is_global = Column(Boolean, default=True)  # True for Hash Pass; False for vendor/cafe pass categor
