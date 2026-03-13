from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from db.extensions import db


class SquadPricingRule(db.Model):
    __tablename__ = "squad_pricing_rules"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    console_group = Column(String(20), nullable=False, index=True)
    player_count = Column(Integer, nullable=False)
    discount_percent = Column(Numeric(6, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vendor_id", "console_group", "player_count", name="uq_squad_rule_vendor_group_players"),
    )
