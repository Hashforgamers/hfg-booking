# models/booking.py
from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

from .availableGame import AvailableGame
from .slot import Slot

class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    game_id = Column(Integer, ForeignKey('available_games.id'), nullable=False)
    slot_id = Column(Integer, ForeignKey('slots.id'), nullable=False)
    status = db.Column(db.String(20), default='pending_verified')  # New field for verification status
    
    # Relationship with AvailableGame (many-to-one)
    game = relationship('AvailableGame', back_populates='bookings')

    # Relationship with Slot (many-to-one)
    slot = relationship('Slot', back_populates='bookings')

    # Add relationship to transactions
    transaction = relationship('Transaction', back_populates='booking', uselist=False)

    def __repr__(self):
        return f"<Booking user_id={self.user_id} game_id={self.game_id}>"

    def to_dict(self):
        return {
            'booking_id': self.id,
            'user_id': self.user_id,
            'status': self.status,
            'slot': self.slot.to_dict_for_booking() if self.slot else None
        }
