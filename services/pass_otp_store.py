"""Database-backed OTP state shared by all booking workers.

Writes participate in the caller's transaction, including consuming a verified
capability together with the booking and pass debit.
"""
import hashlib
from sqlalchemy.ext.mutable import MutableDict
from db.extensions import db


class PassOtpState(db.Model):
    __tablename__ = 'pass_otp_states'
    key = db.Column(db.String(64), primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    payload = db.Column(MutableDict.as_mutable(db.JSON), nullable=False)


class PassOtpStore:
    def __init__(self, kind):
        self.kind = kind

    def _key(self, key):
        return hashlib.sha256((self.kind + ':' + key).encode()).hexdigest()

    def get(self, key):
        row = PassOtpState.query.filter_by(key=self._key(key), kind=self.kind).populate_existing().with_for_update().first()
        if row:
            # SQLAlchemy's identity map holds weak references. Keep the parent alive
            # for in-place attempt-counter updates until this request's session ends.
            db.session.info.setdefault('pass_otp_rows', {})[row.key] = row
        return row.payload if row else None

    def __setitem__(self, key, value):
        db.session.add(PassOtpState(key=self._key(key), kind=self.kind, payload=value))
        db.session.flush()

    def pop(self, key, default=None):
        row = PassOtpState.query.filter_by(key=self._key(key), kind=self.kind).with_for_update().first()
        if row:
            value = dict(row.payload)
            db.session.delete(row)
            db.session.flush()
            return value
        return default

    def live_for(self, vendor_id, user_id, pass_uid, now):
        # Caller holds the user lock to serialize issuance for the same customer.
        rows = PassOtpState.query.filter(
            PassOtpState.kind == self.kind,
            PassOtpState.payload['vendor_id'].as_integer() == vendor_id,
            PassOtpState.payload['user_id'].as_integer() == user_id,
            PassOtpState.payload['pass_uid'].as_string() == pass_uid,
            PassOtpState.payload['expires_at'].as_float() > now,
        ).all()
        for row in rows:
            item = row.payload
            if item.get('expires_at', 0) > now and item.get('vendor_id') == vendor_id and item.get('user_id') == user_id and item.get('pass_uid') == pass_uid:
                return item.get('request_id'), item
        return None, None


def cleanup(now):
    # SQL JSON access works on PostgreSQL and the isolated SQLite tests.
    PassOtpState.query.filter(PassOtpState.payload['expires_at'].as_float() <= now).delete(synchronize_session=False)
