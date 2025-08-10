from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship
from db.extensions import db

class BookingExtraService(db.Model):
    __tablename__ = 'booking_extra_services'

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=False)
    menu_item_id = Column(Integer, ForeignKey('extra_service_menus.id'), nullable=False)

    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    booking = relationship('Booking', back_populates='booking_extra_services')
    menu_item = relationship('ExtraServiceMenu')
