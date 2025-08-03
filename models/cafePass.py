from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from db.extensions import db

class CafePass(db.Model):
    __tablename__ = 'cafe_passes'
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))         # Null if hash pass
    pass_type_id = Column(Integer, ForeignKey('pass_types.id'))   # Links to daily/monthly/yearly type
    name = Column(String(100), nullable=False)                    # e.g., "Platinum Pass", etc.
    price = Column(Float, nullable=False)
    days_valid = Column(Integer, nullable=False)                  # Number of days for the pass validity
    is_active = Column(Boolean, default=True)
    pass_type = relationship('PassType')
    vendor = relationship('Vendor')

    description = Column(String(255))
