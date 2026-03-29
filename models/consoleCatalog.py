from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func
from db.extensions import db


class ConsoleCatalog(db.Model):
    __tablename__ = "console_catalog"

    id = Column(Integer, primary_key=True)
    slug = Column(String(80), nullable=False, unique=True, index=True)
    display_name = Column(String(120), nullable=False)
    family = Column(String(80), nullable=False, default="other")
    icon = Column(String(64), nullable=True)
    input_mode = Column(String(32), nullable=False, default="controller")
    supports_multiplayer = Column(Boolean, nullable=False, default=False)
    default_capacity = Column(Integer, nullable=False, default=1)
    controller_policy = Column(String(32), nullable=False, default="none")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def to_dict(self):
        return {
            "id": int(self.id),
            "slug": self.slug,
            "display_name": self.display_name,
            "family": self.family,
            "icon": self.icon,
            "input_mode": self.input_mode,
            "supports_multiplayer": bool(self.supports_multiplayer),
            "default_capacity": int(self.default_capacity or 1),
            "controller_policy": self.controller_policy,
            "is_active": bool(self.is_active),
            "source": "global",
        }
