import html
# controllers/pass_controller.py
from flask import Blueprint, request, jsonify, current_app, g
from services.pass_service import PassService
from services.vendor_access import require_vendor_permission
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

from services.pass_otp_store import PassOtpStore, cleanup as cleanup_pass_otp
_PASS_OTP_CACHE = PassOtpStore("otp")
_PASS_OTP_VERIFIED_CACHE = PassOtpStore("verified")
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


def _cleanup_pass_otp_cache(now_ts):
    cleanup_pass_otp(now_ts)


def _find_live_otp_session(vendor_id, user_id, pass_uid, now_ts):
    return _PASS_OTP_CACHE.live_for(vendor_id, user_id, pass_uid, now_ts)


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
@require_vendor_permission("booking.manage", "passes.manage")
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
@require_vendor_permission("booking.manage", "passes.manage")
def get_dashboard_user_valid_passes():
    """
    Dashboard helper:
    Return valid hour-based passes for a selected user at a vendor.
    """
    try:
        vendor_id = request.args.get('vendor_id', type=int)
        user_id = request.args.get('user_id', type=int)
        hours_needed = request.args.get('hours_needed', type=float)
        slot_ids = [int(value) for value in request.args.get('slot_ids', '').split(',') if value]
        if len(slot_ids) > 20 or len(set(slot_ids)) != len(slot_ids) or any(value <= 0 for value in slot_ids):
            return jsonify(message='Supply up to 20 distinct slot IDs'), 400
        if hours_needed is not None and (not Decimal(str(hours_needed)).is_finite() or hours_needed < 0):
            return jsonify(message='Invalid hours_needed'), 400
        if slot_ids:
            from models.slot import Slot
            from models.availableGame import AvailableGame
            valid_count = Slot.query.join(AvailableGame, Slot.gaming_type_id == AvailableGame.id).filter(
                Slot.id.in_(slot_ids), AvailableGame.vendor_id == vendor_id).count()
            if valid_count != len(slot_ids):
                return jsonify(message='Slots must belong to this cafe'), 400
        from services.payment_methods import accepted_methods
        enabled = accepted_methods(vendor_id)


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

            method = 'hash_global_pass' if is_global else 'cafe_specific_pass'
            if method not in enabled:
                continue
            required_hours = float(sum((PassService.calculate_slot_hours(sid, cafe_pass) for sid in slot_ids), Decimal('0'))) if slot_ids else hours_needed
            can_cover_hours = True
            shortfall = 0.0
            if required_hours is not None and required_hours > 0:
                can_cover_hours = remaining_hours >= float(required_hours)
                shortfall = max(float(required_hours) - remaining_hours, 0.0)

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
                "required_hours": required_hours,
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
    except (ValueError, TypeError) as error:
        return jsonify(message=str(error)), 400
    except Exception as e:
        current_app.logger.error("Dashboard valid-pass fetch failed: %s", e)
        return jsonify({
            "success": False,
            "message": "Failed to fetch valid passes",
            "error": str(e),
        }), 500


@pass_blueprint.route('/pass/dashboard/otp/send', methods=['POST'])
@require_vendor_permission("booking.manage", "passes.manage")
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

        User.query.filter_by(id=user_id).with_for_update().first()
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
                "request_id": otp_session_id,
                "vendor_id": int(vendor_id),
                "user_id": int(user_id),
                "pass_uid": pass_uid,
                "otp_hash": _hash_otp(otp_code),
                "created_at": now_ts,
                "expires_at": now_ts + _PASS_OTP_TTL_SECONDS,
                "attempts_remaining": _PASS_OTP_MAX_ATTEMPTS,
            }

        db.session.commit()
        vendor = Vendor.query.filter_by(id=int(vendor_id)).first()
        vendor_name = vendor.cafe_name if vendor else f"Vendor #{vendor_id}"
        subject = "Verify your pass redemption | Hash For Gamers"
        plain_body = (
            f"Hello {user.name},\n\n"
            f"Your OTP for pass redemption at {vendor_name} is {otp_code}.\n"
            f"This OTP is valid for {_PASS_OTP_TTL_SECONDS // 60} minutes.\n\n"
            f"If this wasn't you, ignore this message."
        )
        html_fragment = f"""
            <p style="margin:0 0 12px 0;">Hello <strong>{html.escape(str(user.name))}</strong>,</p>
            <p style="margin:0 0 12px 0;">Use this verification code to redeem your pass at <strong>{html.escape(str(vendor_name))}</strong>:</p>
            <div style="font-size:30px;letter-spacing:5px;font-weight:700;color:#22c55e;margin:10px 0 14px 0;">{otp_code}</div>
            <p style="margin:0 0 10px 0;color:#cbd5e1;">Pass UID: <strong>{html.escape(str(pass_uid))}</strong></p>
            <p style="margin:0;color:#cbd5e1;">This OTP expires in <strong>{_PASS_OTP_TTL_SECONDS // 60} minutes</strong>.</p>
            <p style="color:#94a3b8;font-size:13px;">Do not share this code. If you did not request it, no action is required.</p>
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
@require_vendor_permission("booking.manage", "passes.manage")
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

            if int(session.get("vendor_id", 0)) != g.vendor_id:
                return jsonify(error="OTP belongs to another cafe"), 403
            stored_hash = str(session.get("otp_hash") or "")
            input_hash = _hash_otp(raw_otp)
            if not hmac.compare_digest(stored_hash, input_hash):
                attempts_remaining = int(session.get("attempts_remaining", 1)) - 1
                session["attempts_remaining"] = attempts_remaining
                if attempts_remaining <= 0:
                    _PASS_OTP_CACHE.pop(otp_session_id, None)
                    db.session.commit()
                    return jsonify({"success": False, "message": "OTP attempts exceeded. Request a new OTP"}), 400

                db.session.commit()
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

        db.session.commit()
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
@require_vendor_permission("booking.manage", "passes.manage")
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
    # Confirmation performs the booking and debit in one transaction.
    return jsonify(error='Redeem your pass through booking confirmation using payment_mode=hour_pass and pass_uid.'), 409


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
@auth_required_self(decrypt_user=True)
def get_pass_history(user_pass_id):
    """
    Get redemption history for a pass.
    """
    try:
        if not UserPass.query.filter_by(id=user_pass_id, user_id=g.auth_user_id).first():
            return jsonify(error="Pass not found"), 404
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
@auth_required_self(decrypt_user=True)
def cancel_redemption(redemption_id):
    return jsonify(error='Use booking cancellation to restore eligible pass hours. Direct restoration is not supported.'), 409


@pass_blueprint.route('/pass/create-hour-pass', methods=['POST'])
@pass_blueprint.route('/user/passes/purchase', methods=['POST'])
@auth_required_self(decrypt_user=True)
def purchase_pass():
    from services.pass_purchase_service import purchase, PurchaseError
    from sqlalchemy.exc import IntegrityError
    try:
        if getattr(g, 'token_expired', False):
            return jsonify(error='Sign in again'), 401
        owned, transaction_id, replay = purchase(g.auth_user_id, request.get_json(silent=True))
        db.session.commit()
        return jsonify(success=True, user_pass=owned.to_dict(), transaction_id=transaction_id,
                       idempotent=replay), 200 if replay else 201
    except PurchaseError as error:
        db.session.rollback()
        return jsonify(error=str(error)), error.status
    except ValueError as error:
        db.session.rollback()
        return jsonify(error=str(error)), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify(error='Payment or request already used. Retry with the same request key.'), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Pass purchase failed')
        return jsonify(error='Pass purchase failed'), 500


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
