from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint

from db.extensions import db


class VendorTaxProfile(db.Model):
    __tablename__ = "vendor_tax_profiles"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)

    gst_registered = Column(Boolean, nullable=False, default=False)
    gstin = Column(String(20), nullable=True)
    legal_name = Column(String(255), nullable=True)

    state_code = Column(String(2), nullable=True)
    place_of_supply_state_code = Column(String(2), nullable=True)

    gst_enabled = Column(Boolean, nullable=False, default=False)
    gst_rate = Column(Float, nullable=False, default=18.0)
    tax_inclusive = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vendor_id", name="uq_vendor_tax_profile_vendor"),
    )

    def to_dict(self):
        return {
            "vendor_id": self.vendor_id,
            "gst_registered": self.gst_registered,
            "gstin": self.gstin,
            "legal_name": self.legal_name,
            "state_code": self.state_code,
            "place_of_supply_state_code": self.place_of_supply_state_code,
            "gst_enabled": self.gst_enabled,
            "gst_rate": float(self.gst_rate or 0),
            "tax_inclusive": self.tax_inclusive,
        }
