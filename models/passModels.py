# models/pass_models.py
"""
All pass-related models in one file to avoid circular dependencies
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, Numeric, Date, DateTime, Time, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from db.extensions import db
import secrets
import string
import pytz

IST = pytz.timezone("Asia/Kolkata")


# ==========================================
# PASS TYPE MODEL
# ==========================================
class PassType(db.Model):
    __tablename__ = 'pass_types'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255))
    is_global = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<PassType id={self.id} name={self.name}>"


# ==========================================
# CAFE PASS MODEL
# ==========================================
class CafePass(db.Model):
    __tablename__ = 'cafe_passes'
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=True, index=True)
    pass_type_id = Column(Integer, ForeignKey('pass_types.id'))
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True, index=True)
    
    # Both pass types need validity period
    days_valid = Column(Integer, nullable=False)  # ✅ FIXED: Not nullable
    
    # Hour-based pass fields
    pass_mode = Column(String(20), nullable=False, default='date_based', index=True)
    total_hours = Column(Numeric(precision=10, scale=2), nullable=True)
    hour_calculation_mode = Column(String(20), nullable=True)
    hours_per_slot = Column(Numeric(precision=5, scale=2), nullable=True)
    
    # Relationships
    pass_type = relationship('PassType', backref='cafe_passes')
    vendor = relationship('Vendor', backref='cafe_passes')
    
    def __repr__(self):
        return f"<CafePass id={self.id} name={self.name} mode={self.pass_mode}>"
    
    def validate(self):
        """Validate pass configuration"""
        if self.pass_mode == 'hour_based':
            if not self.total_hours or self.total_hours <= 0:
                raise ValueError("Hour-based pass must have total_hours > 0")
            
            if self.hour_calculation_mode not in ['actual_duration', 'vendor_config']:
                raise ValueError("Invalid hour_calculation_mode")
            
            if self.hour_calculation_mode == 'vendor_config':
                if not self.hours_per_slot or self.hours_per_slot <= 0:
                    raise ValueError("vendor_config mode requires hours_per_slot > 0")
        
        if not self.days_valid or self.days_valid <= 0:
            raise ValueError("Pass must have days_valid > 0")
        
        return True
    
    def to_dict(self):
        return {
            'id': self.id,
            'vendor_id': self.vendor_id,
            'pass_type_id': self.pass_type_id,
            'name': self.name,
            'price': self.price,
            'description': self.description,
            'is_active': self.is_active,
            'pass_mode': self.pass_mode,
            'days_valid': self.days_valid,
            'total_hours': float(self.total_hours) if self.total_hours else None,
            'hour_calculation_mode': self.hour_calculation_mode,
            'hours_per_slot': float(self.hours_per_slot) if self.hours_per_slot else None,
            'pass_type': self.pass_type.name if self.pass_type else None
        }


# ==========================================
# USER PASS MODEL
# ==========================================
class UserPass(db.Model):
    __tablename__ = 'user_passes'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    cafe_pass_id = Column(Integer, ForeignKey('cafe_passes.id'), nullable=False, index=True)
    purchased_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True, index=True)
    
    # Date-based pass fields
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True, index=True)  # ✅ FIXED: Added index
    
    # Hour-based pass fields
    pass_mode = Column(String(20), nullable=False, default='date_based', index=True)
    pass_uid = Column(String(20), unique=True, nullable=True, index=True)
    total_hours = Column(Numeric(precision=10, scale=2), nullable=True)
    remaining_hours = Column(Numeric(precision=10, scale=2), nullable=True)
    
    # Relationships
    cafe_pass = relationship('CafePass', backref='user_passes')
    user = relationship('User', backref='user_passes')
    redemption_logs = relationship(
        'PassRedemptionLog',
        back_populates='user_pass',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )
    
    def __repr__(self):
        return f"<UserPass id={self.id} user_id={self.user_id} mode={self.pass_mode} uid={self.pass_uid}>"
    
    @staticmethod
    def generate_pass_uid(length=12):
        """Generate unique pass UID for hour-based passes"""
        chars = string.ascii_uppercase + string.digits
        return 'HFG-' + ''.join(secrets.choice(chars) for _ in range(length))
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'cafe_pass_id': self.cafe_pass_id,
            'cafe_pass_name': self.cafe_pass.name if self.cafe_pass else None,
            'pass_type': self.cafe_pass.pass_type.name if self.cafe_pass and self.cafe_pass.pass_type else None,  # ✅ FIXED: Added pass_type
            'vendor_id': self.cafe_pass.vendor_id if self.cafe_pass else None,
            'purchased_at': self.purchased_at.isoformat() if self.purchased_at else None,
            'is_active': self.is_active,
            'pass_mode': self.pass_mode,
            'valid_from': self.valid_from.isoformat() if self.valid_from else None,
            'valid_to': self.valid_to.isoformat() if self.valid_to else None,
            'pass_uid': self.pass_uid,
            'total_hours': float(self.total_hours) if self.total_hours else None,
            'remaining_hours': float(self.remaining_hours) if self.remaining_hours else None,
        }


# ==========================================
# PASS REDEMPTION LOG MODEL
# ==========================================
class PassRedemptionLog(db.Model):
    __tablename__ = 'pass_redemption_logs'
    
    id = Column(Integer, primary_key=True)
    user_pass_id = Column(Integer, ForeignKey('user_passes.id'), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=True, index=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    hours_deducted = Column(Numeric(precision=10, scale=2), nullable=False)
    session_start_time = Column(Time, nullable=True)
    session_end_time = Column(Time, nullable=True)
    
    redemption_method = Column(String(20), nullable=False)
    redeemed_by_staff_id = Column(Integer, nullable=True)
    redeemed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(IST), nullable=False, index=True)
    notes = Column(Text, nullable=True)
    
    is_cancelled = Column(Boolean, default=False, nullable=False, index=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user_pass = relationship('UserPass', back_populates='redemption_logs')
    booking = relationship('Booking', backref='pass_redemptions')
    vendor = relationship('Vendor', foreign_keys=[vendor_id], backref='pass_redemptions')
    user = relationship('User', foreign_keys=[user_id], backref='pass_redemptions')
    
    def __repr__(self):
        return f"<PassRedemptionLog id={self.id} pass_id={self.user_pass_id} hours={self.hours_deducted}>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_pass_id': self.user_pass_id,
            'booking_id': self.booking_id,
            'vendor_id': self.vendor_id,
            'user_id': self.user_id,
            'user_name': self.user.name if self.user else None,  # ✅ FIXED: Added user_name
            'hours_deducted': float(self.hours_deducted),
            'session_start_time': self.session_start_time.strftime('%H:%M:%S') if self.session_start_time else None,
            'session_end_time': self.session_end_time.strftime('%H:%M:%S') if self.session_end_time else None,
            'redemption_method': self.redemption_method,
            'redeemed_by_staff_id': self.redeemed_by_staff_id,
            'redeemed_at': self.redeemed_at.isoformat() if self.redeemed_at else None,
            'notes': self.notes,
            'is_cancelled': self.is_cancelled,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
        }
