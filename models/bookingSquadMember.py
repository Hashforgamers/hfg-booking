from sqlalchemy import Column, Integer, ForeignKey, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime


class BookingSquadMember(db.Model):
    __tablename__ = "booking_squad_members"

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    member_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    member_position = Column(Integer, nullable=False)  # 1 = captain, 2+ = squad members
    is_captain = Column(Boolean, nullable=False, default=False)
    name_snapshot = Column(String(255), nullable=False)
    phone_snapshot = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    booking = relationship("Booking", back_populates="squad_members")
    member_user = relationship("User", foreign_keys=[member_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "member_user_id": self.member_user_id,
            "member_position": self.member_position,
            "is_captain": self.is_captain,
            "name": self.name_snapshot,
            "phone": self.phone_snapshot,
        }
