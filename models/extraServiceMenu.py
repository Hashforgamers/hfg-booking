from sqlalchemy import Column, Integer, ForeignKey, String, Boolean, Float
from sqlalchemy.orm import relationship
from db.extensions import db

class ExtraServiceMenu(db.Model):
    __tablename__ = 'extra_service_menus'

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('extra_service_categories.id'), nullable=False)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(500))
    is_active = Column(Boolean, default=True)
    stock_quantity = Column(Integer, nullable=True)
    stock_unit = Column(String(32), nullable=False, default='units')
    low_stock_threshold = Column(Integer, nullable=False, default=0)

    category = relationship('ExtraServiceCategory', back_populates='menus')
    booking_extra_services = relationship('BookingExtraService', back_populates='extra_service_menu')
    images = relationship('ExtraServiceMenuImage', back_populates='menu_item')
