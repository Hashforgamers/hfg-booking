from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint

from db.extensions import db


class TimeWalletAccount(db.Model):
    __tablename__ = "time_wallet_accounts"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    balance_minutes = Column(Integer, nullable=False, default=0)
    balance_amount = Column(Float, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vendor_id", "user_id", name="uq_time_wallet_vendor_user"),
    )


class TimeWalletLedger(db.Model):
    __tablename__ = "time_wallet_ledgers"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("time_wallet_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)

    entry_type = Column(String(30), nullable=False)  # credit/debit/expire/adjustment
    minutes = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0)
    description = Column(String(255), nullable=True)

    source_channel = Column(String(20), nullable=False, default="app")
    staff_id = Column(String(100), nullable=True)
    staff_name = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
