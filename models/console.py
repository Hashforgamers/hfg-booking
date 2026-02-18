# app/models/console.py
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db
from models.availableGame import available_game_console

class Console(db.Model):
    __tablename__ = 'consoles'

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id', ondelete='CASCADE'), nullable=False, index=True)  # NEW
    console_number = Column(Integer, nullable=False, index=True)
    model_number = Column(String(50), nullable=False)
    serial_number = Column(String(100), nullable=False)
    brand = Column(String(50), nullable=False)
    console_type = Column(String(50), nullable=False)  # 'pc', 'ps5', etc.
    release_date = Column(Date, nullable=True)
    description = Column(String(500), nullable=True)

    vendor = relationship('Vendor', back_populates='consoles')  # NEW

    hardware_specifications = relationship('HardwareSpecification', back_populates='console', uselist=False, cascade="all, delete-orphan")
    maintenance_status = relationship('MaintenanceStatus', back_populates='console', uselist=False, cascade="all, delete-orphan")
    price_and_cost = relationship('PriceAndCost', back_populates='console', uselist=False, cascade="all, delete-orphan")
    additional_details = relationship('AdditionalDetails', back_populates='console', uselist=False, cascade="all, delete-orphan")

    available_games = relationship('AvailableGame', secondary='available_game_console', back_populates='consoles')

    def __repr__(self):
        return f"<Console vendor_id={self.vendor_id} number={self.console_number} type={self.console_type}>"
