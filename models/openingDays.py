from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class OpeningDay(db.Model):
    __tablename__ = 'opening_days'

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False)  # Ensure this exists
    day = Column(String(10), nullable=False)  # e.g., 'mon', 'tues', etc.
    is_open = Column(Boolean, default=False)  # Indicates if the vendor is open on this day

    def __str__(self):
        return f"OpeningDay(id={self.id}, day='{self.day}', is_open={self.is_open})"

    def __repr__(self):
        return self.__str__()