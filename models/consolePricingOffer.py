# models/consolePricingOffer.py
from sqlalchemy import Column, Integer, String, Numeric, Date, Time, Boolean, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, date, time as dt_time
from db.extensions import db


class ConsolePricingOffer(db.Model):
    """
    Time-based promotional pricing for console types (AvailableGames)
    Allows vendors to set special prices for specific date/time ranges
    """
    __tablename__ = 'console_pricing_offers'
    
    id = Column(Integer, primary_key=True)
    
    # Foreign Keys
    vendor_id = Column(Integer, ForeignKey('vendors.id', ondelete='CASCADE'), nullable=False, index=True)
    available_game_id = Column(Integer, ForeignKey('available_games.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Pricing
    default_price = Column(Numeric(10, 2), nullable=False)  # Regular price (copied from AvailableGame)
    offered_price = Column(Numeric(10, 2), nullable=False)  # Promotional price
    
    # Validity Period
    start_date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_date = Column(Date, nullable=False, index=True)
    end_time = Column(Time, nullable=False)
    
    # Offer Details
    offer_name = Column(String(100), nullable=False)  # e.g., "Weekend Special", "Happy Hours"
    offer_description = Column(String(255), nullable=True)  # Optional description
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    vendor = relationship('Vendor', backref='pricing_offers')
    available_game = relationship('AvailableGame', backref='pricing_offers')
    
    # Constraints
    __table_args__ = (
        CheckConstraint('offered_price <= default_price', name='check_offered_price_lte_default'),
        CheckConstraint('end_date >= start_date', name='check_end_date_gte_start'),
    )
    
    def __repr__(self):
        return f"<ConsolePricingOffer vendor_id={self.vendor_id} game={self.available_game.game_name if self.available_game else 'N/A'} offer='{self.offer_name}'>"
    
    def is_currently_active(self):
        """
        Check if this offer is active RIGHT NOW
        Returns True if current datetime falls within the offer period
        """
        if not self.is_active:
            return False
        
        now = datetime.now()
        current_date = now.date()
        current_time = now.time()
        
        # Check if current date is within range
        if not (self.start_date <= current_date <= self.end_date):
            return False
        
        # Single day offer
        if self.start_date == self.end_date:
            return self.start_time <= current_time <= self.end_time
        
        # Multi-day offer
        if current_date == self.start_date:
            # First day: check if time is after start_time
            return current_time >= self.start_time
        elif current_date == self.end_date:
            # Last day: check if time is before end_time
            return current_time <= self.end_time
        else:
            # Middle days: always active
            return True
    
    def get_discount_percentage(self):
        """Calculate discount percentage"""
        if self.default_price <= 0:
            return 0
        discount = float(self.default_price) - float(self.offered_price)
        return round((discount / float(self.default_price)) * 100, 1)
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'vendor_id': self.vendor_id,
            'available_game_id': self.available_game_id,
            'console_type': self.available_game.game_name if self.available_game else None,
            'default_price': float(self.default_price),
            'offered_price': float(self.offered_price),
            'discount_percentage': self.get_discount_percentage(),
            'start_date': self.start_date.isoformat(),
            'start_time': self.start_time.strftime('%H:%M'),
            'end_date': self.end_date.isoformat(),
            'end_time': self.end_time.strftime('%H:%M'),
            'offer_name': self.offer_name,
            'offer_description': self.offer_description,
            'is_active': self.is_active,
            'is_currently_active': self.is_currently_active(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
