"""Permission checks for staff credit operations, using signed vendor tokens."""
from functools import wraps

import jwt
from flask import current_app, jsonify, request


def vendor_id_from_claims(claims):
    vendor = claims.get("vendor") or {}
    subject = claims.get("sub") or {}
    value = claims.get("vendor_id")
    if value is None and isinstance(vendor, dict):
        value = vendor.get("id")
    if value is None and isinstance(subject, dict):
        value = subject.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def permits(claims, vendor_id, permissions):
    if vendor_id_from_claims(claims) != vendor_id:
        return False
    if claims.get("scope") == "vendor_access":
        staff = claims.get("staff") or {}
        return bool(set(staff.get("permissions") or []) & set(permissions))
    # Match the dashboard service's signed legacy owner-token support.
    return claims.get("scope") is None


def require_vendor_permission(*permissions):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify(success=False, error="Please sign in again."), 401
            try:
                claims = jwt.decode(
                    auth[7:], current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"],
                    options={"require": ["exp", "iat"], "verify_sub": False},
                )
            except jwt.InvalidTokenError:
                return jsonify(success=False, error="Session expired or invalid. Please sign in again."), 401
            if not permits(claims, kwargs.get("vendor_id"), permissions):
                return jsonify(success=False, error="You do not have permission for this credit operation."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate
