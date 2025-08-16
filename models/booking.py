# models/booking.py
from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime
import pytz

from .availableGame import AvailableGame
from .slot import Slot
from .accessBookingCode import AccessBookingCode

# Helper function to return current IST time
def current_time_ist():
    return datetime.now(pytz.timezone("Asia/Kolkata"))

class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    game_id = Column(Integer, ForeignKey('available_games.id'), nullable=False)
    slot_id = Column(Integer, ForeignKey('slots.id'), nullable=False)
    status = db.Column(db.String(20), default='pending_verified')

    # ✅ Auto timestamps with IST
    created_at = Column(DateTime(timezone=True), default=current_time_ist, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=current_time_ist, onupdate=current_time_ist, nullable=False)

    # Relationships
    game = relationship('AvailableGame', back_populates='bookings')
    slot = relationship('Slot', back_populates='bookings')
    transaction = relationship('Transaction', back_populates='booking', uselist=False)
    booking_extra_services = relationship('BookingExtraService', back_populates='booking', cascade='all, delete-orphan')
    access_code_id = Column(Integer, ForeignKey('access_booking_codes.id'), nullable=True)
    access_code_entry = db.relationship('AccessBookingCode', back_populates='bookings')

    def __repr__(self):
        return f"<Booking user_id={self.user_id} game_id={self.game_id}>"

    def to_dict(self):
        return {
            'booking_id': self.id,
            'user_id': self.user_id,
            'status': self.status,
            'slot': self.slot.to_dict_for_booking() if self.slot else None,
            'access_code': self.access_code_entry.access_code if self.access_code_entry else None,
            'book_date': self.transaction.booked_date.isoformat() if self.transaction else None,
            'created_at': self.created_at.astimezone(pytz.timezone("Asia/Kolkata")).isoformat() if self.created_at else None,
            'updated_at': self.updated_at.astimezone(pytz.timezone("Asia/Kolkata")).isoformat() if self.updated_at else None,
            'extra_services': [
                {
                    'id': bes.extra_service_menu.id,
                    'name': bes.extra_service_menu.name,
                    'price': bes.extra_service_menu.price,
                    'quantity': bes.quantity,
                    'total_price': bes.total_price,
                    'images': [
                        {
                            'id': img.id,
                            'image_url': img.image_url,
                            'public_id': img.public_id,
                            'alt_text': img.alt_text,
                            'is_primary': img.is_primary
                        } for img in bes.extra_service_menu.images if img.is_active
                    ]
                } for bes in self.booking_extra_services
            ]
        }
