from sqlalchemy import Column, Integer, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from db.extensions import db

class ExtraServiceCategory(db.Model):
    __tablename__ = 'extra_service_categories'

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    is_active = Column(Boolean, default=True)

    vendor = relationship('Vendor', back_populates='extra_service_categories')
    menus = relationship('ExtraServiceMenu', back_populates='category', cascade='all, delete-orphan')
