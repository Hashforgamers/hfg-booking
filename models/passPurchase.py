from datetime import datetime
from db.extensions import db


class PassPurchase(db.Model):
    __tablename__ = 'pass_purchases'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    idempotency_key = db.Column(db.String(100), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    user_pass_id = db.Column(db.Integer, nullable=False)
    transaction_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'idempotency_key', name='uq_pass_purchase_request'),)
