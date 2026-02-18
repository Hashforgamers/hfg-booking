from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import relationship
from db.extensions import db
from models.vendor import Vendor  # Replace .vendor with the correct path to Vendor+

# ✅ Define the association table before using it in the models
available_game_console = Table(
    'available_game_console',
    db.Model.metadata,
    Column('available_game_id', Integer, ForeignKey('available_games.id'), primary_key=True),
    Column('console_id', Integer, ForeignKey('consoles.id'), primary_key=True)
)


class AvailableGame(db.Model):
    __tablename__ = 'available_games'
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)
    game_name = Column(String(50), nullable=False)
    total_slot = Column(Integer, nullable=False)
    single_slot_price = Column(Integer, nullable=False)
    
    vendor = relationship('Vendor', back_populates='available_games')

    # Relationship with Slot (one-to-many)
    slots = relationship('Slot', back_populates='available_game', cascade="all, delete-orphan")

    # Relationship with Booking (one-to-many)
    bookings = relationship('Booking', back_populates='game', cascade="all, delete-orphan")
    
    consoles = relationship('Console', secondary='available_game_console', back_populates='available_games')

    def to_dict_for_booking(self):
        return {
            'game_id': self.id,
            'vendor_id': self.vendor_id,
            'game_name': self.game_name,
            'single_slot_price': self.single_slot_price,
            'cafe_name':self.vendor.to_dict_for_booking()
        }