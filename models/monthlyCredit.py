from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint

from db.extensions import db


class MonthlyCreditAccount(db.Model):
    __tablename__ = "monthly_credit_accounts"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    credit_limit = Column(Float, nullable=False, default=0)
    outstanding_amount = Column(Float, nullable=False, default=0)
    billing_cycle_day = Column(Integer, nullable=False, default=1)
    grace_days = Column(Integer, nullable=False, default=5)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(String(255), nullable=True)

    # Recovery/KYC metadata for trusted monthly-credit users
    customer_name = Column(String(255), nullable=True)
    whatsapp_number = Column(String(20), nullable=True)
    phone_number = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    address_line1 = Column(String(255), nullable=True)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(20), nullable=True)
    id_proof_type = Column(String(50), nullable=True)
    id_proof_number = Column(String(100), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vendor_id", "user_id", name="uq_monthly_credit_vendor_user"),
    )


class MonthlyCreditLedger(db.Model):
    __tablename__ = "monthly_credit_ledgers"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("monthly_credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)

    entry_type = Column(String(30), nullable=False)  # charge/payment/adjustment
    amount = Column(Float, nullable=False, default=0)
    description = Column(String(255), nullable=True)
    booked_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)

    source_channel = Column(String(20), nullable=False, default="app")
    staff_id = Column(String(100), nullable=True)
    staff_name = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
