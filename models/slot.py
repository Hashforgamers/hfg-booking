# models/slot.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Date, Time
from sqlalchemy.orm import relationship
from db.extensions import db


class Slot(db.Model):
    __tablename__ = 'slots'

    id = db.Column(db.Integer, primary_key=True)
    gaming_type_id = Column(Integer, ForeignKey('available_games.id'), nullable=False)
    start_time = db.Column(Time, nullable=False)
    end_time = db.Column(Time, nullable=False)
    available_slot = Column(Integer, nullable=False)
    is_available = db.Column(Boolean, default=True)

    # Relationship with AvailableGame (many-to-one)
    available_game = relationship('AvailableGame', back_populates='slots')

    # Relationship with Booking (one-to-many)
    bookings = relationship('Booking', back_populates='slot', cascade="all, delete-orphan")

    
    def __repr__(self):
        return f"<Slot available_game_id={self.gaming_type_id} time_bracket={self.start_time} - {self.end_time}>"

    def to_dict(self):
        """Return a dictionary representation of the Slot object."""
        return {
            'id': self.id,
            'gaming_type_id': self.gaming_type_id,
            'time':{
                'start_time': str(self.start_time),
                'end_time': str(self.end_time),
            },
            'available_slot': self.available_slot,
            'is_available': self.is_available
        }

    def to_dict_for_booking(self):
        """Return a dictionary representation of the Slot object."""
        return {
            'slot_id': self.id,
            'gaming_type_id': self.available_game.to_dict_for_booking() if self.available_game else None,
            'time':{
                'start_time': str(self.start_time),
                'end_time': str(self.end_time),
            }
        }
