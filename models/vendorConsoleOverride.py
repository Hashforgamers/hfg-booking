from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from db.extensions import db


class VendorConsoleOverride(db.Model):
    __tablename__ = "vendor_console_overrides"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    console_catalog_id = Column(Integer, ForeignKey("console_catalog.id", ondelete="SET NULL"), nullable=True, index=True)

    slug = Column(String(80), nullable=True)
    display_name = Column(String(120), nullable=True)
    family = Column(String(80), nullable=True)
    icon = Column(String(64), nullable=True)
    input_mode = Column(String(32), nullable=True)
    supports_multiplayer = Column(Boolean, nullable=True)
    default_capacity = Column(Integer, nullable=True)
    controller_policy = Column(String(32), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("vendor_id", "slug", name="uq_vendor_console_override_slug"),
    )
