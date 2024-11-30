from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime

# Vendor model
class Vendor(db.Model):
    __tablename__ = 'vendors'
    
    id = Column(Integer, primary_key=True)
    cafe_name = Column(String(255), nullable=False)

    available_games = relationship('AvailableGame', back_populates='vendor', cascade="all, delete-orphan")

    def to_dict_for_booking(self):
        return {
            "cafe_name":self.cafe_name
        }