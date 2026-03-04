from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship

from db.extensions import db


class ControllerPricingTier(db.Model):
    __tablename__ = "controller_pricing_tiers"

    id = Column(Integer, primary_key=True)
    rule_id = Column(
        Integer,
        ForeignKey("controller_pricing_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity = Column(Integer, nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    rule = relationship("ControllerPricingRule", back_populates="tiers")

    __table_args__ = (
        UniqueConstraint("rule_id", "quantity", name="uq_controller_tier_rule_quantity"),
        CheckConstraint("quantity >= 2", name="check_controller_tier_quantity_gte_2"),
        CheckConstraint("total_price >= 0", name="check_controller_tier_total_price_gte_0"),
    )
