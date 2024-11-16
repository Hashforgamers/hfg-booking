from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class AvailableGame(db.Model):
    __tablename__ = 'available_games'
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    game_name = Column(String(50), nullable=False)
    total_slot = Column(Integer, nullable=False)
    single_slot_price = Column(Integer, nullable=False)
    
    # Relationship with Slot (one-to-many)
    slots = relationship('Slot', back_populates='available_game', cascade="all, delete-orphan")

    # Relationship with Booking (one-to-many)
    bookings = relationship('Booking', back_populates='game', cascade="all, delete-orphan")

    def to_dict_for_booking(self):
        return {
            'game_id': self.id,
            'vendor_id': self.vendor_id,
            'game_name': self.game_name,
            'single_slot_price': self.single_slot_price
        }