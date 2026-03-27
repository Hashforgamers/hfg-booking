# controllers/pass_controller.py
from flask import Blueprint, request, jsonify, current_app, g
from services.pass_service import PassService
from services.security import auth_required_self
from services.mail_service import send_email
from db.extensions import db
from models.passModels import UserPass, CafePass, PassRedemptionLog
from models.user import User
from models.vendor import Vendor
from models.transaction import Transaction
from decimal import Decimal
from datetime import datetime, timedelta, time as time_type
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
import hashlib
import hmac
import razorpay
import pytz
import time
import os
import requests
import secrets
import uuid
from threading import Lock


IST = pytz.timezone("Asia/Kolkata")


pass_blueprint = Blueprint('pass', __name__)
_AVAILABLE_PASSES_CACHE = {}
_AVAILABLE_PASSES_TTL_SECONDS = int(os.getenv("AVAILABLE_PASSES_CACHE_TTL_SEC", "120"))
_AVAILABLE_PASSES_CACHE_MAX_ITEMS = 1000
_AVAILABLE_PASSES_CACHE_LOCK = Lock()

_PASS_OTP_CACHE = {}
_PASS_OTP_VERIFIED_CACHE = {}
_PASS_OTP_CACHE_LOCK = Lock()
_PASS_OTP_TTL_SECONDS = int(os.getenv("PASS_BOOKING_OTP_TTL_SECONDS", "300"))
_PASS_OTP_VERIFY_TTL_SECONDS = int(os.getenv("PASS_BOOKING_VERIFY_TTL_SECONDS", "900"))
_PASS_OTP_MAX_ATTEMPTS = int(os.getenv("PASS_BOOKING_OTP_MAX_ATTEMPTS", "5"))
_PASS_OTP_RATE_LIMIT_SECONDS = int(os.getenv("PASS_BOOKING_OTP_RATE_LIMIT_SECONDS", "30"))
_PASS_BOOKING_REQUIRE_OTP = os.getenv("PASS_BOOKING_REQUIRE_OTP", "true").lower() in ("true", "1", "t", "yes", "y")
_PASS_BOOKING_OTP_PUSH_ENABLED = os.getenv("PASS_BOOKING_OTP_PUSH_ENABLED", "true").lower() in ("true", "1", "t", "yes", "y")
_USER_NOTIFICATION_ENDPOINT = os.getenv(
    "USER_NOTIFICATION_ENDPOINT",
    "https://hfg-user-onboard.onrender.com/api/users/notifications/demo",
)


def _passes_cache_get(vendor_id, now_ts):
    with _AVAILABLE_PASSES_CACHE_LOCK:
        item = _AVAILABLE_PASSES_CACHE.get(vendor_id)
        if not item:
            return None
        if (now_ts - item["ts"]) >= _AVAILABLE_PASSES_TTL_SECONDS:
            _AVAILABLE_PASSES_CACHE.pop(vendor_id, None)
            return None
        return item["payload"]


def _passes_cache_set(vendor_id, payload, now_ts):
    with _AVAILABLE_PASSES_CACHE_LOCK:
        if len(_AVAILABLE_PASSES_CACHE) >= _AVAILABLE_PASSES_CACHE_MAX_ITEMS:
            _AVAILABLE_PASSES_CACHE.clear()
        _AVAILABLE_PASSES_CACHE[vendor_id] = {"ts": now_ts, "payload": payload}


def _mask_email(email: str) -> str:
    value = str(email or "").strip()
    if not value or "@" not in value:
        return "hidden"
    username, domain = value.split("@", 1)
    if not username:
        return f"***@{domain}"
    if len(username) <= 2:
        masked_user = f"{username[0]}*"
    else:
        masked_user = f"{username[0]}{'*' * (len(username) - 2)}{username[-1]}"
    return f"{masked_user}@{domain}"


def _otp_secret() -> str:
    return str(
        current_app.config.get("SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or "hfg-pass-otp-secret"
    )


def _hash_otp(raw_otp: str) -> str:
    payload = f"{_otp_secret()}::{str(raw_otp or '').strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cleanup_pass_otp_cache(now_ts: float):
    expired_otp_ids = [sid for sid, item in _PASS_OTP_CACHE.items() if float(item.get("expires_at", 0)) <= now_ts]
    for sid in expired_otp_ids:
        _PASS_OTP_CACHE.pop(sid, None)
    expired_verified_ids = [tid for tid, item in _PASS_OTP_VERIFIED_CACHE.items() if float(item.get("expires_at", 0)) <= now_ts]
    for tid in expired_verified_ids:
        _PASS_OTP_VERIFIED_CACHE.pop(tid, None)


def _find_live_otp_session(vendor_id: int, user_id: int, pass_uid: str, now_ts: float):
    for session_id, session in _PASS_OTP_CACHE.items():
        if float(session.get("expires_at", 0)) <= now_ts:
            continue
        if (
            int(session.get("vendor_id", -1)) == int(vendor_id)
            and int(session.get("user_id", -1)) == int(user_id)
            and str(session.get("pass_uid", "")).strip().upper() == str(pass_uid or "").strip().upper()
        ):
            return session_id, session
    return None, None


def _send_pass_otp_push(user_id: int, vendor_name: str, pass_uid: str, otp_code: str):
    if not _PASS_BOOKING_OTP_PUSH_ENABLED:
        return {"sent": False, "reason": "push_disabled"}
    try:
        payload = {
            "user_id": int(user_id),
            "title": "Pass OTP Verification",
            "message": f"OTP {otp_code} for {vendor_name} booking. Pass {pass_uid}.",
            "invite_status": "pending",
            "reference_id": f"pass-otp-{uuid.uuid4()}",
        }
        response = requests.post(_USER_NOTIFICATION_ENDPOINT, json=payload, timeout=3)
        ok = response.status_code < 400
        return {"sent": ok, "status_code": response.status_code}
    except Exception as exc:
        current_app.logger.warning("Pass OTP push notification failed: %s", exc)
        return {"sent": False, "reason": "exception"}


def _consume_pass_verification_token(token: str, vendor_id: int, user_id: int, pass_uid: str):
    token_value = str(token or "").strip()
    if not token_value:
        return False, "pass_verification_token is required"

    now_ts = time.time()
    pass_uid_normalized = str(pass_uid or "").strip().upper()

    with _PASS_OTP_CACHE_LOCK:
        _cleanup_pass_otp_cache(now_ts)
        session = _PASS_OTP_VERIFIED_CACHE.get(token_value)
        if not session:
            return False, "Invalid or expired pass verification token"

        if int(session.get("vendor_id", -1)) != int(vendor_id):
            return False, "Pass verification token vendor mismatch"
        if int(session.get("user_id", -1)) != int(user_id):
            return False, "Pass verification token user mismatch"
        if str(session.get("pass_uid", "")).strip().upper() != pass_uid_normalized:
            return False, "Pass verification token pass mismatch"

        _PASS_OTP_VERIFIED_CACHE.pop(token_value, None)

    return True, None


@pass_blueprint.route('/pass/validate', methods=['POST'])
def validate_pass():
    """
    Validate pass UID and return pass details.
    Used by dashboard before redemption.
    """
    try:
        data = request.get_json()
        pass_uid = str(data.get('pass_uid') or '').strip()
        vendor_id_raw = data.get('vendor_id')
        try:
            vendor_id = int(vendor_id_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'vendor_id must be a valid integer'}), 400
        
        if not pass_uid or not vendor_id:
            return jsonify({'error': 'pass_uid and vendor_id required'}), 400
        
        # Find pass
        user_pass = UserPass.query.filter_by(
            pass_uid=pass_uid,
            is_active=True,
            pass_mode='hour_based'
        ).first()
        
        if not user_pass:
            return jsonify({
                'valid': False,
                'error': 'Invalid or inactive pass'
            }), 404
        
        # Check expiry
        if user_pass.valid_to and user_pass.valid_to < datetime.now(IST).date():
            return jsonify({
                'valid': False,
                'error': 'Pass expired'
            }), 400
        
        # Check hours
        if user_pass.remaining_hours <= 0:
            return jsonify({
                'valid': False,
                'error': 'No hours remaining'
            }), 400
        
        # Check vendor compatibility
        cafe_pass = CafePass.query.get(user_pass.cafe_pass_id)
        if not cafe_pass:
            return jsonify({
                'valid': False,
                'error': 'Associated pass configuration not found'
            }), 404
        
        # Vendor-specific pass must match vendor
        if cafe_pass.vendor_id is not None:
            if cafe_pass.vendor_id != vendor_id:
                return jsonify({
                    'valid': False,
                    'error': 'Pass not valid at this vendor'
                }), 400
        # If vendor_id is None, it's a global pass (valid everywhere)
        
        # Return pass details
        return jsonify({
            'valid': True,
            'pass': {
                'id': user_pass.id,
                'pass_uid': user_pass.pass_uid,
                'user_id': user_pass.user_id,
                'pass_name': cafe_pass.name,
                'total_hours': float(user_pass.total_hours),
                'remaining_hours': float(user_pass.remaining_hours),
                'valid_from': user_pass.valid_from.isoformat() if user_pass.valid_from else None,
                'valid_to': user_pass.valid_to.isoformat() if user_pass.valid_to else None,
                'is_global': cafe_pass.vendor_id is None,
                'vendor_id': cafe_pass.vendor_id,
                'hour_calculation_mode': cafe_pass.hour_calculation_mode,
                'hours_per_slot': float(cafe_pass.hours_per_slot) if cafe_pass.hours_per_slot else None
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Pass validation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/pass/dashboard/valid-options', methods=['GET'])
def get_dashboard_user_valid_passes():
    """
    Dashboard helper:
    Return valid hour-based passes for a selected user at a vendor.
    """
    try:
        vendor_id = request.args.get('vendor_id', type=int)
        user_id = request.args.get('user_id', type=int)
        hours_needed = request.args.get('hours_needed', type=float)

        if not vendor_id or not user_id:
            return jsonify({
                "success": False,
                "message": "vendor_id and user_id are required",
            }), 400

        user = (
            User.query
            .options(joinedload(User.contact_info))
            .filter(User.id == int(user_id))
            .first()
        )
        if not user:
            return jsonify({
                "success": False,
                "message": "User not found",
            }), 404

        today = datetime.now(IST).date()
        raw_passes = PassService.get_user_active_passes(user_id=int(user_id), vendor_id=int(vendor_id))
        valid_passes = []
        for user_pass in raw_passes:
            if str(user_pass.pass_mode or "").lower() != "hour_based":
                continue

            remaining_hours = float(user_pass.remaining_hours or 0)
            if remaining_hours <= 0:
                continue
            if user_pass.valid_to and user_pass.valid_to < today:
                continue

            cafe_pass = user_pass.cafe_pass
            if not cafe_pass or not cafe_pass.is_active:
                continue

            is_global = cafe_pass.vendor_id is None
            can_use_here = is_global or int(cafe_pass.vendor_id) == int(vendor_id)
            if not can_use_here:
                continue

            can_cover_hours = True
            shortfall = 0.0
            if hours_needed is not None and hours_needed > 0:
                can_cover_hours = remaining_hours >= float(hours_needed)
                shortfall = max(float(hours_needed) - remaining_hours, 0.0)

            valid_passes.append({
                "id": int(user_pass.id),
                "pass_uid": user_pass.pass_uid,
                "user_id": int(user_pass.user_id),
                "pass_name": cafe_pass.name,
                "total_hours": float(user_pass.total_hours or 0),
                "remaining_hours": remaining_hours,
                "valid_from": user_pass.valid_from.isoformat() if user_pass.valid_from else None,
                "valid_to": user_pass.valid_to.isoformat() if user_pass.valid_to else None,
                "is_global": bool(is_global),
                "vendor_id": cafe_pass.vendor_id,
                "hours_per_slot": float(cafe_pass.hours_per_slot) if cafe_pass.hours_per_slot else None,
                "can_cover_hours": bool(can_cover_hours),
                "hours_shortfall": round(shortfall, 2),
            })

        valid_passes.sort(
            key=lambda row: (
                0 if row.get("can_cover_hours") else 1,
                -(row.get("remaining_hours") or 0),
            )
        )

        return jsonify({
            "success": True,
            "user": {
                "id": int(user.id),
                "name": user.name,
                "email": user.contact_info.email if user.contact_info else None,
                "phone": user.contact_info.phone if user.contact_info else None,
            },
            "vendor_id": int(vendor_id),
            "hours_needed": round(float(hours_needed), 2) if hours_needed is not None else None,
            "passes": valid_passes,
            "count": len(valid_passes),
        }), 200
    except Exception as e:
        current_app.logger.error("Dashboard valid-pass fetch failed: %s", e)
        return jsonify({
            "success": False,
            "message": "Failed to fetch valid passes",
            "error": str(e),
        }), 500


@pass_blueprint.route('/pass/dashboard/otp/send', methods=['POST'])
def send_dashboard_pass_otp():
    """
    Send one-time OTP (mail + optional push) before pass redemption from dashboard.
    """
    try:
        data = request.get_json(silent=True) or {}
        vendor_id = int(data.get("vendor_id"))
        user_id = int(data.get("user_id"))
        pass_uid = str(data.get("pass_uid") or "").strip().upper()

        if not pass_uid:
            return jsonify({"success": False, "message": "pass_uid is required"}), 400

        user_pass = PassService.get_valid_user_pass(
            user_id=None,
            vendor_id=vendor_id,
            pass_uid=pass_uid,
        )
        if not user_pass:
            return jsonify({"success": False, "message": "Pass not found or not valid"}), 404
        if int(user_pass.user_id) != int(user_id):
            return jsonify({"success": False, "message": "Pass does not belong to selected user"}), 400

        user = (
            User.query
            .options(joinedload(User.contact_info))
            .filter(User.id == int(user_id))
            .first()
        )
        if not user or not user.contact_info or not user.contact_info.email:
            return jsonify({"success": False, "message": "User email not found for OTP delivery"}), 400

        now_ts = time.time()
        with _PASS_OTP_CACHE_LOCK:
            _cleanup_pass_otp_cache(now_ts)
            existing_session_id, existing_session = _find_live_otp_session(vendor_id, user_id, pass_uid, now_ts)
            if existing_session:
                elapsed = now_ts - float(existing_session.get("created_at", now_ts))
                if elapsed < _PASS_OTP_RATE_LIMIT_SECONDS:
                    retry_after = int(max(_PASS_OTP_RATE_LIMIT_SECONDS - elapsed, 1))
                    return jsonify({
                        "success": False,
                        "message": f"Please wait {retry_after}s before requesting another OTP",
                        "retry_after_seconds": retry_after,
                    }), 429
                if existing_session_id:
                    _PASS_OTP_CACHE.pop(existing_session_id, None)

            otp_code = f"{secrets.randbelow(1_000_000):06d}"
            otp_session_id = str(uuid.uuid4())
            _PASS_OTP_CACHE[otp_session_id] = {
                "vendor_id": int(vendor_id),
                "user_id": int(user_id),
                "pass_uid": pass_uid,
                "otp_hash": _hash_otp(otp_code),
                "created_at": now_ts,
                "expires_at": now_ts + _PASS_OTP_TTL_SECONDS,
                "attempts_remaining": _PASS_OTP_MAX_ATTEMPTS,
            }

        vendor = Vendor.query.filter_by(id=int(vendor_id)).first()
        vendor_name = vendor.cafe_name if vendor else f"Vendor #{vendor_id}"
        subject = "Pass OTP Verification • Hash For Gamers"
        plain_body = (
            f"Hi {user.name},\n\n"
            f"Your OTP for pass redemption at {vendor_name} is {otp_code}.\n"
            f"This OTP is valid for {_PASS_OTP_TTL_SECONDS // 60} minutes.\n\n"
            f"If this wasn't you, ignore this message."
        )
        html_fragment = f"""
            <p style="margin:0 0 12px 0;">Hi <strong>{user.name}</strong>,</p>
            <p style="margin:0 0 12px 0;">Your OTP for pass redemption at <strong>{vendor_name}</strong> is:</p>
            <div style="font-size:30px;letter-spacing:8px;font-weight:700;color:#22c55e;margin:10px 0 14px 0;">{otp_code}</div>
            <p style="margin:0 0 10px 0;color:#cbd5e1;">Pass UID: <strong>{pass_uid}</strong></p>
            <p style="margin:0;color:#cbd5e1;">This OTP expires in <strong>{_PASS_OTP_TTL_SECONDS // 60} minutes</strong>.</p>
        """
        send_email(subject=subject, recipients=[user.contact_info.email], body=plain_body, html_fragment=html_fragment)

        push_result = _send_pass_otp_push(
            user_id=int(user_id),
            vendor_name=vendor_name,
            pass_uid=pass_uid,
            otp_code=otp_code,
        )

        return jsonify({
            "success": True,
            "message": "OTP sent successfully",
            "otp_request_id": otp_session_id,
            "expires_in_seconds": _PASS_OTP_TTL_SECONDS,
            "masked_email": _mask_email(user.contact_info.email),
            "delivery": {
                "email": True,
                "push": bool(push_result.get("sent")),
            },
        }), 200
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "vendor_id and user_id must be valid integers"}), 400
    except Exception as e:
        current_app.logger.error("Failed to send pass OTP: %s", e)
        return jsonify({
            "success": False,
            "message": "Failed to send pass OTP",
            "error": str(e),
        }), 500


@pass_blueprint.route('/pass/dashboard/otp/verify', methods=['POST'])
def verify_dashboard_pass_otp():
    """
    Verify OTP and return short-lived pass_verification_token for redemption.
    """
    try:
        data = request.get_json(silent=True) or {}
        otp_session_id = str(data.get("otp_request_id") or "").strip()
        raw_otp = str(data.get("otp") or "").strip()

        if not otp_session_id or not raw_otp:
            return jsonify({"success": False, "message": "otp_request_id and otp are required"}), 400

        now_ts = time.time()
        with _PASS_OTP_CACHE_LOCK:
            _cleanup_pass_otp_cache(now_ts)
            session = _PASS_OTP_CACHE.get(otp_session_id)
            if not session:
                return jsonify({"success": False, "message": "OTP session expired or invalid"}), 400

            stored_hash = str(session.get("otp_hash") or "")
            input_hash = _hash_otp(raw_otp)
            if not hmac.compare_digest(stored_hash, input_hash):
                attempts_remaining = int(session.get("attempts_remaining", 1)) - 1
                session["attempts_remaining"] = attempts_remaining
                if attempts_remaining <= 0:
                    _PASS_OTP_CACHE.pop(otp_session_id, None)
                    return jsonify({"success": False, "message": "OTP attempts exceeded. Request a new OTP"}), 400

                return jsonify({
                    "success": False,
                    "message": "Invalid OTP",
                    "attempts_remaining": attempts_remaining,
                }), 400

            verification_token = secrets.token_urlsafe(24)
            _PASS_OTP_VERIFIED_CACHE[verification_token] = {
                "vendor_id": int(session.get("vendor_id")),
                "user_id": int(session.get("user_id")),
                "pass_uid": str(session.get("pass_uid") or "").strip().upper(),
                "expires_at": now_ts + _PASS_OTP_VERIFY_TTL_SECONDS,
            }
            _PASS_OTP_CACHE.pop(otp_session_id, None)

        return jsonify({
            "success": True,
            "message": "OTP verified successfully",
            "pass_verification_token": verification_token,
            "expires_in_seconds": _PASS_OTP_VERIFY_TTL_SECONDS,
        }), 200
    except Exception as e:
        current_app.logger.error("Failed to verify pass OTP: %s", e)
        return jsonify({
            "success": False,
            "message": "Failed to verify OTP",
            "error": str(e),
        }), 500


@pass_blueprint.route('/pass/redeem/dashboard', methods=['POST'])
def redeem_pass_dashboard():
    """
    Redeem pass from dashboard (vendor scans pass).
    Staff ID removed - vendor scans directly.
    """
    try:
        data = request.get_json()
        pass_uid = str(data.get('pass_uid') or '').strip().upper()
        vendor_id_raw = data.get('vendor_id')
        hours_to_deduct = data.get('hours_to_deduct')
        session_start = data.get('session_start')  # HH:MM format
        session_end = data.get('session_end')      # HH:MM format
        notes = data.get('notes')
        pass_verification_token = str(
            data.get("pass_verification_token") or data.get("passVerificationToken") or ""
        ).strip()

        try:
            vendor_id = int(vendor_id_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'vendor_id must be a valid integer'}), 400
        
        if not all([pass_uid, vendor_id, hours_to_deduct]):
            return jsonify({'error': 'pass_uid, vendor_id, and hours_to_deduct required'}), 400
        
        try:
            hours_decimal = Decimal(str(hours_to_deduct))
            if hours_decimal <= 0:
                return jsonify({'error': 'hours_to_deduct must be positive'}), 400
        except:
            return jsonify({'error': 'Invalid hours_to_deduct format'}), 400
        
        # Parse times if provided
        start_time = None
        end_time = None
        if session_start:
            try:
                start_time = datetime.strptime(session_start, '%H:%M').time()
            except:
                return jsonify({'error': 'Invalid session_start format (use HH:MM)'}), 400
        if session_end:
            try:
                end_time = datetime.strptime(session_end, '%H:%M').time()
            except:
                return jsonify({'error': 'Invalid session_end format (use HH:MM)'}), 400
        
        # ✅ Get pass using updated PassService
        user_pass = PassService.get_valid_user_pass(
            user_id=None,  # Not needed for pass_uid lookup
            vendor_id=vendor_id,
            pass_uid=pass_uid
        )
        
        if not user_pass:
            return jsonify({'error': f'Pass {pass_uid} not found or invalid'}), 404
        
        if _PASS_BOOKING_REQUIRE_OTP:
            token_ok, token_error = _consume_pass_verification_token(
                token=pass_verification_token,
                vendor_id=vendor_id,
                user_id=int(user_pass.user_id),
                pass_uid=pass_uid,
            )
            if not token_ok:
                return jsonify({'error': token_error}), 400

        # ✅ Redeem using PassService (no staff_id)
        redemption = PassService.redeem_pass_hours(
            user_pass_id=user_pass.id,
            vendor_id=vendor_id,
            hours_to_deduct=hours_decimal,
            redemption_method='dashboard_manual',
            session_start=start_time,
            session_end=end_time,
            redeemed_by_staff_id=None,
            notes=notes
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Pass redeemed successfully',
            'redemption': redemption.to_dict(),
            'remaining_hours': float(user_pass.remaining_hours),
            'is_depleted': user_pass.remaining_hours <= 0
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Dashboard redemption error: {str(e)}")
        return jsonify({'error': 'Redemption failed'}), 500


@pass_blueprint.route('/pass/redeem/app', methods=['POST'])
@auth_required_self(decrypt_user=True)
def redeem_pass_app():
    """
    Redeem pass during app booking flow.
    Called during booking confirmation.
    """
    try:
        user_id = g.auth_user_id
        data = request.get_json()
        
        vendor_id = data.get('vendor_id')
        slot_id = data.get('slot_id')
        pass_uid = data.get('pass_uid')  # Optional: specific pass
        booking_id = data.get('booking_id')
        
        if not all([vendor_id, slot_id, booking_id]):
            return jsonify({'error': 'vendor_id, slot_id, and booking_id required'}), 400
        
        # Get pass (specific or best available)
        user_pass = PassService.get_valid_user_pass(
            user_id=user_id,
            vendor_id=vendor_id,
            pass_uid=pass_uid
        )
        
        if not user_pass:
            return jsonify({'error': 'No valid pass found'}), 404
        
        # Get cafe_pass for calculation
        cafe_pass = CafePass.query.get(user_pass.cafe_pass_id)
        if not cafe_pass:
            return jsonify({'error': 'Pass configuration not found'}), 404
        
        # Calculate hours based on slot and pass config
        hours_to_deduct = PassService.calculate_slot_hours(
            slot_id=slot_id,
            cafe_pass=cafe_pass
        )
        
        # Get slot times
        from models.slot import Slot
        slot = Slot.query.get(slot_id)
        
        # Redeem
        redemption = PassService.redeem_pass_hours(
            user_pass_id=user_pass.id,
            vendor_id=vendor_id,
            hours_to_deduct=hours_to_deduct,
            redemption_method='app_booking',
            booking_id=booking_id,
            session_start=slot.start_time if slot else None,
            session_end=slot.end_time if slot else None,
            redeemed_by_staff_id=None
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Pass redeemed for booking',
            'redemption': redemption.to_dict(),
            'hours_deducted': float(hours_to_deduct),
            'remaining_hours': float(user_pass.remaining_hours),
            'pass_uid': user_pass.pass_uid
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"App redemption error: {str(e)}")
        return jsonify({'error': 'Redemption failed'}), 500


@pass_blueprint.route('/pass/user/active', methods=['GET'])
@auth_required_self(decrypt_user=True)
def get_user_active_passes():
    """
    Get all active passes for authenticated user.
    """
    try:
        user_id = g.auth_user_id
        vendor_id = request.args.get('vendor_id', type=int)
        
        passes = PassService.get_user_active_passes(user_id, vendor_id)
        
        return jsonify({
            'passes': [p.to_dict() for p in passes]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get active passes error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/pass/<int:user_pass_id>/history', methods=['GET'])
def get_pass_history(user_pass_id):
    """
    Get redemption history for a pass.
    """
    try:
        logs = PassRedemptionLog.query.filter_by(
            user_pass_id=user_pass_id
        ).order_by(PassRedemptionLog.redeemed_at.desc()).all()
        
        return jsonify({
            'history': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get pass history error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/pass/redemption/<int:redemption_id>/cancel', methods=['POST'])
def cancel_redemption(redemption_id):
    """
    Cancel a redemption and restore hours.
    """
    try:
        data = request.get_json()
        reason = data.get('reason')
        
        success = PassService.cancel_redemption(redemption_id, reason)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Redemption cancelled and hours restored'
            }), 200
        else:
            return jsonify({'error': 'Cancellation failed'}), 500
            
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Cancel redemption error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/pass/create-hour-pass', methods=['POST'])
@auth_required_self(decrypt_user=True)
def create_hour_pass():
    """
    Create hour-based pass after purchase (called after payment confirmation).
    """
    try:
        user_id = g.auth_user_id
        data = request.get_json()
        
        cafe_pass_id = data.get('cafe_pass_id')
        payment_details = data.get('payment_details')
        
        if not cafe_pass_id:
            return jsonify({'error': 'cafe_pass_id required'}), 400
        
        user_pass = PassService.create_hour_based_pass(
            user_id=user_id,
            cafe_pass_id=cafe_pass_id,
            payment_details=payment_details
        )
        
        return jsonify({
            'success': True,
            'message': 'Hour-based pass created',
            'pass': user_pass.to_dict()
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create hour pass error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/user/passes/purchase', methods=['POST'])
def purchase_pass():
    """
    User purchases a pass after Razorpay payment.
    Creates UserPass record with unique pass_uid.
    """
    try:
        data = request.get_json()
        
        user_id = data.get('user_id')
        cafe_pass_id = data.get('cafe_pass_id')
        payment_id = data.get('payment_id', f'test_pay_{int(datetime.now(IST).timestamp())}')
        payment_mode = data.get('payment_mode', 'payment_gateway')
        
        if not all([user_id, cafe_pass_id]):
            return jsonify({'error': 'user_id and cafe_pass_id required'}), 400
        
        # Get cafe pass
        cafe_pass = CafePass.query.get(cafe_pass_id)
        if not cafe_pass or not cafe_pass.is_active:
            return jsonify({'error': 'Pass not available'}), 404
        
        # ✅ TESTING MODE - Skip Razorpay verification
        if payment_mode == 'payment_gateway':
            current_app.logger.info(f"[TEST MODE] Skipping Razorpay verification for payment_id: {payment_id}")
            # In production, uncomment the verification code below:
            """
            if not payment_id:
                return jsonify({'error': 'payment_id required'}), 400
            
            try:
                RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
                RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")
                razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                
                payment = razorpay_client.payment.fetch(payment_id)
                if payment['status'] != 'captured':
                    return jsonify({'error': 'Payment not successful'}), 400
                    
            except Exception as e:
                current_app.logger.error(f"Razorpay verification failed: {str(e)}")
                return jsonify({'error': f'Payment verification failed: {str(e)}'}), 400
            """
        
        # Deduct from wallet if wallet payment
        elif payment_mode == 'wallet':
            from models.user import User
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if user.wallet_balance < cafe_pass.price:
                return jsonify({'error': 'Insufficient wallet balance'}), 400
            user.wallet_balance -= cafe_pass.price
        
        # Create UserPass based on pass_mode
        if cafe_pass.pass_mode == 'hour_based':
            # Use PassService for hour-based
            user_pass = PassService.create_hour_based_pass(
                user_id=user_id,
                cafe_pass_id=cafe_pass_id,
                payment_details={'payment_id': payment_id, 'mode': payment_mode}
            )
        else:
            # Create date-based pass
            valid_from = datetime.now(IST).date()
            valid_to = valid_from + timedelta(days=cafe_pass.days_valid)
            
            user_pass = UserPass(
                user_id=user_id,
                cafe_pass_id=cafe_pass_id,
                pass_mode='date_based',
                valid_from=valid_from,
                valid_to=valid_to,
                is_active=True,
                purchased_at=datetime.now(IST)
            )
            db.session.add(user_pass)
            db.session.flush()
        
        # Create transaction record
        transaction = Transaction(
            user_id=user_id,
            vendor_id=cafe_pass.vendor_id,
            user_name=user_pass.user.name if hasattr(user_pass, 'user') and user_pass.user else None,
            original_amount=cafe_pass.price,
            discounted_amount=0,
            amount=cafe_pass.price,
            mode_of_payment=payment_mode,
            booking_date=datetime.now(IST).date(),
            booking_time=datetime.now(IST).time(),
            reference_id=payment_id,
        )
        db.session.add(transaction)
        db.session.commit()
        
        current_app.logger.info(
            f"Pass purchased: user_id={user_id} pass_id={user_pass.id} "
            f"amount={cafe_pass.price} payment={payment_mode}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Pass purchased successfully',
            'user_pass': user_pass.to_dict(),
            'transaction_id': transaction.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Pass purchase failed: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pass_blueprint.route('/vendor/<int:vendor_id>/passes/available', methods=['GET'])
def get_available_passes_for_purchase(vendor_id):
    """
    Get all active passes available for purchase at a vendor.
    Used by user app to show passes for sale.
    """
    try:
        started_at = time.perf_counter()
        now = time.time()
        cached_payload = _passes_cache_get(vendor_id, now)
        if cached_payload is not None:
            response = jsonify(cached_payload)
            response.headers["X-Cache"] = "HIT"
            response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
            return response, 200

        # Get vendor-specific AND global passes
        passes = (
            CafePass.query
            .options(joinedload(CafePass.pass_type))
            .filter(
                CafePass.is_active == True,
                or_(
                    CafePass.vendor_id == vendor_id,
                    CafePass.vendor_id.is_(None)  # Global passes
                )
            )
            .order_by(CafePass.pass_mode, CafePass.price)
            .all()
        )
        
        payload = {
            'passes': [p.to_dict() for p in passes]
        }
        _passes_cache_set(vendor_id, payload, now)
        response = jsonify(payload)
        response.headers["X-Cache"] = "MISS"
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
        return response, 200
        
    except Exception as e:
        current_app.logger.error(f"Get available passes error: {str(e)}")
        return jsonify({'error': str(e)}), 500
