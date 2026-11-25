"""Contact details for walk-in gamers who have no phone or email (e.g. kids).

A gamer booked at the counter may have only a name. We store NULL for the
missing phone/email once `sql/20261125_contact_info_optional_phone_email.sql`
has been applied. Until then the columns are still NOT NULL, so we fall back
to unique, clearly fake values that can never be dialled, emailed or matched
by a lookup (the old code used a random 10-digit number or "0000000000",
which could belong to a real person and merged unrelated walk-ins).
"""
import time
import uuid

from flask import current_app
from sqlalchemy.sql import text

from db.extensions import db

PLACEHOLDER_EMAIL_DOMAIN = "@hash.local"
PLACEHOLDER_PHONE_PREFIX = "nophone-"
_LEGACY_PLACEHOLDER_PHONES = {"0000000000"}

_NULLABLE_CACHE = {"value": None, "checked_at": 0.0}
_RECHECK_SECONDS = 300


def contact_columns_nullable() -> bool:
    """True once contact_info.phone and .email accept NULL (cached)."""
    cached = _NULLABLE_CACHE["value"]
    if cached is True:
        return True
    if cached is False and time.monotonic() - _NULLABLE_CACHE["checked_at"] < _RECHECK_SECONDS:
        return False
    try:
        rows = db.session.execute(
            text(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'contact_info' AND column_name IN ('phone', 'email')
                """
            )
        ).fetchall()
        value = len(rows) == 2 and all(str(r[1]).upper() == "YES" for r in rows)
    except Exception as err:  # pragma: no cover - defensive
        current_app.logger.warning("contact_info nullability check failed: %s", err)
        value = False
    _NULLABLE_CACHE["value"] = value
    _NULLABLE_CACHE["checked_at"] = time.monotonic()
    return value


def is_placeholder_email(value) -> bool:
    email = str(value or "").strip().lower()
    return not email or email.endswith(PLACEHOLDER_EMAIL_DOMAIN)


def is_placeholder_phone(value) -> bool:
    phone = str(value or "").strip()
    if not phone or phone in _LEGACY_PLACEHOLDER_PHONES:
        return True
    return phone.lower().startswith(PLACEHOLDER_PHONE_PREFIX)


def public_email(value):
    """Email to show or send to; None for missing/placeholder values."""
    return None if is_placeholder_email(value) else str(value).strip()


def public_phone(value):
    """Phone to show or contact; None for missing/placeholder values."""
    return None if is_placeholder_phone(value) else str(value).strip()


def storable_contact(phone, email):
    """Return (phone, email) to write to contact_info for a new gamer.

    Missing values become NULL, or unique non-contactable placeholders while
    the columns are still NOT NULL.
    """
    phone = str(phone or "").strip() or None
    email = str(email or "").strip().lower() or None
    if phone and email:
        return phone, email
    if contact_columns_nullable():
        return phone, email
    token = uuid.uuid4().hex[:12]
    return (
        phone or f"{PLACEHOLDER_PHONE_PREFIX}{token}",
        email or f"noemail_{token}{PLACEHOLDER_EMAIL_DOMAIN}",
    )

