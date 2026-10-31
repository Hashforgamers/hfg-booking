from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime

# Vendor model
class Vendor(db.Model):
    __tablename__ = 'vendors'
    
    id = Column(Integer, primary_key=True)
    cafe_name = Column(String(255), nullable=False)
    display_name = Column(String(120), nullable=True)

    @property
    def public_name(self):
        return (self.display_name or '').strip() or self.cafe_name


    available_games = relationship('AvailableGame', back_populates='vendor', cascade="all, delete-orphan")

    # Add relationship to transactions
    transactions = relationship('Transaction', back_populates='vendor', cascade="all, delete-orphan")

    extra_service_categories = relationship('ExtraServiceCategory', back_populates='vendor', cascade='all, delete-orphan')
    
    consoles = relationship('Console', back_populates='vendor', cascade="all, delete-orphan")

    def to_dict_for_booking(self):
        return {
            "cafe_name": self.public_name,
            "display_name": self.display_name
        }