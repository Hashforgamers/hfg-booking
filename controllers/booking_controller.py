from flask import Blueprint, request, jsonify, current_app, g,  make_response
from services.booking_service import BookingService
from db.extensions import db
from models.slot import Slot
from models.booking import Booking
from models.booking import Booking
import logging
import random
import os
from rq import Queue
from rq_scheduler import Scheduler
from sqlalchemy import func
from models.transaction import Transaction
from models.availableGame import AvailableGame, available_game_console
from models.vendor import Vendor
from models.user import User
from models.contactInfo import ContactInfo
from models.console import Console
from models.voucher import Voucher
from models.voucherRedemptionLog import VoucherRedemptionLog
from models.paymentTransactionMapping import PaymentTransactionMapping
from models.userHashCoin import UserHashCoin
from models.accessBookingCode import AccessBookingCode
from models.bookingExtraService  import BookingExtraService
from models.bookingSquadMember import BookingSquadMember
from models.extraServiceCategory import ExtraServiceCategory
from models.extraServiceMenu import ExtraServiceMenu
from models.passModels import UserPass
from models.consolePricingOffer import ConsolePricingOffer
from models.controllerPricingRule import ControllerPricingRule
from models.controllerPricingTier import ControllerPricingTier  # noqa: F401 (mapper registration)
from models.vendorTaxProfile import VendorTaxProfile
from models.squadPricingRule import SquadPricingRule
from models.timeWallet import TimeWalletAccount, TimeWalletLedger
from models.monthlyCredit import MonthlyCreditAccount, MonthlyCreditLedger
from datetime import datetime, timedelta, timezone, date
import pytz
from flask import current_app, jsonify
from sqlalchemy.orm import joinedload

IST = pytz.timezone("Asia/Kolkata")

# Squad platform policy (backend source of truth).
# Discount rule-engine applies only to PC squad bookings.
SQUAD_PLATFORM_RULES = {
    "pc": {"enabled": True, "max_players": 10, "pricing_mode": "squad_discount"},
    "ps": {"enabled": True, "max_players": 4, "pricing_mode": "controller_pricing"},
    "xbox": {"enabled": True, "max_players": 4, "pricing_mode": "controller_pricing"},
    "vr": {"enabled": False, "max_players": 1, "pricing_mode": "solo_only"},
}

DEFAULT_SQUAD_PRICING_POLICY = {
    "pc": {2: 0, 3: 3, 4: 5, 5: 8, 6: 10, 7: 12, 8: 15, 9: 18, 10: 20},
}

from sqlalchemy.sql import text
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, distinct
from services.mail_service import booking_mail, reject_booking_mail, extra_booking_time_mail

from models.hashWallet import HashWallet
from models.hashWalletTransaction import HashWalletTransaction
import time
import json
import base64
import requests
import hmac
import hashlib
import razorpay
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from services.security import auth_required_self

from utils.realtime import build_booking_event_payload
from utils.realtime import emit_booking_event

import uuid

from utils.common import generate_fid, generate_access_code, get_razorpay_keys

booking_blueprint = Blueprint('bookings', __name__)
_ASYNC_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="booking-bg")



def get_effective_price(vendor_id: int, available_game) -> float:
    """
    Returns offered_price if an active pricing offer exists right now,
    otherwise returns the default single_slot_price.
    """
    now_ist = datetime.now(IST)
    current_date = now_ist.date()
    current_time = now_ist.time().replace(tzinfo=None)

    current_offer = (
        ConsolePricingOffer.query
        .filter(
            ConsolePricingOffer.vendor_id == vendor_id,
            ConsolePricingOffer.available_game_id == available_game.id,
            ConsolePricingOffer.is_active == True,
            ConsolePricingOffer.start_date <= current_date,
            ConsolePricingOffer.end_date >= current_date,
            or_(
                and_(
                    ConsolePricingOffer.start_date == ConsolePricingOffer.end_date,
                    ConsolePricingOffer.start_time <= current_time,
                    ConsolePricingOffer.end_time >= current_time
                ),
                and_(
                    ConsolePricingOffer.start_date == current_date,
                    ConsolePricingOffer.end_date > current_date,
                    ConsolePricingOffer.start_time <= current_time
                ),
                and_(
                    ConsolePricingOffer.start_date < current_date,
                    ConsolePricingOffer.end_date == current_date,
                    ConsolePricingOffer.end_time >= current_time
                ),
                and_(
                    ConsolePricingOffer.start_date < current_date,
                    ConsolePricingOffer.end_date > current_date
                )
            )
        )
        .order_by(ConsolePricingOffer.offered_price.asc())
        .first()
    )
    if current_offer is not None:
        return float(current_offer.offered_price)
    return float(available_game.single_slot_price)


def get_effective_price_for_schedule(vendor_id: int, available_game, booking_date, slot_obj=None) -> float:
    """
    Returns offered price for the selected booking date/slot window if an active pricing
    offer exists for that schedule. Falls back to the game base price.
    """
    if not available_game:
        return 0.0

    try:
        if isinstance(booking_date, str):
            booking_date = datetime.strptime(booking_date, "%Y-%m-%d").date()
    except ValueError:
        return float(available_game.single_slot_price or 0.0)

    slot_start = getattr(slot_obj, "start_time", None)
    slot_end = getattr(slot_obj, "end_time", None)

    query = (
        ConsolePricingOffer.query
        .filter(
            ConsolePricingOffer.vendor_id == vendor_id,
            ConsolePricingOffer.available_game_id == available_game.id,
            ConsolePricingOffer.is_active == True,
            ConsolePricingOffer.start_date <= booking_date,
            ConsolePricingOffer.end_date >= booking_date,
        )
    )

    if slot_start is not None and slot_end is not None:
        query = query.filter(
            or_(
                and_(
                    ConsolePricingOffer.start_date == ConsolePricingOffer.end_date,
                    ConsolePricingOffer.start_time <= slot_start,
                    ConsolePricingOffer.end_time >= slot_end,
                ),
                and_(
                    ConsolePricingOffer.start_date == booking_date,
                    ConsolePricingOffer.end_date > booking_date,
                    ConsolePricingOffer.start_time <= slot_start,
                ),
                and_(
                    ConsolePricingOffer.start_date < booking_date,
                    ConsolePricingOffer.end_date == booking_date,
                    ConsolePricingOffer.end_time >= slot_end,
                ),
                and_(
                    ConsolePricingOffer.start_date < booking_date,
                    ConsolePricingOffer.end_date > booking_date,
                )
            )
        )

    current_offer = query.order_by(ConsolePricingOffer.offered_price.asc()).first()
    if current_offer is not None:
        return float(current_offer.offered_price)
    return float(available_game.single_slot_price or 0.0)


def _resolve_available_game_for_vendor(vendor_id: int, console_type: str = None, console_id: int = None, game_id: int = None):
    """
    Resolve the available game row using explicit game_id first, then console_id, then console type.
    Mirrors the dashboard booking resolution strategy so app preview stays aligned.
    """
    resolved_game = None

    if game_id:
        resolved_game = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id, id=game_id).first()
        if resolved_game:
            return resolved_game

    if console_id:
        resolved_game = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id, id=console_id).first()
        if resolved_game:
            return resolved_game

    console_type_lower = str(console_type or "").strip().lower()
    if not console_type_lower:
        return db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).first()

    pattern_groups = {
        "pc": ["%pc%", "%gaming%", "%computer%"],
        "ps5": ["%ps5%", "%playstation%", "%sony%"],
        "ps": ["%ps%", "%playstation%", "%sony%"],
        "xbox": ["%xbox%", "%microsoft%"],
        "vr": ["%vr%", "%virtual%", "%reality%"],
    }

    for pattern in pattern_groups.get(console_type_lower, [f"%{console_type_lower}%"]):
        resolved_game = db.session.query(AvailableGame).filter(
            AvailableGame.vendor_id == vendor_id,
            AvailableGame.game_name.ilike(pattern)
        ).first()
        if resolved_game:
            return resolved_game

    return db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).first()


def calculate_extra_controller_fare(vendor_id: int, available_game_id: int, quantity: int):
    """
    Calculate controller fare using tiered pricing rules.
    If no rule exists, returns None and caller may fallback to legacy fare.
    """
    if quantity <= 0:
        return 0.0

    rule = ControllerPricingRule.query.filter_by(
        vendor_id=vendor_id,
        available_game_id=available_game_id,
        is_active=True
    ).first()

    if not rule:
        return None

    base_price = float(rule.base_price or 0)
    active_tiers = sorted(
        [tier for tier in rule.tiers if tier.is_active],
        key=lambda t: t.quantity
    )

    # Minimum-cost composition: base controller price + any active bundle tiers.
    dp = [float("inf")] * (quantity + 1)
    dp[0] = 0.0

    for q in range(1, quantity + 1):
        dp[q] = min(dp[q], dp[q - 1] + base_price)
        for tier in active_tiers:
            if tier.quantity <= q:
                dp[q] = min(dp[q], dp[q - tier.quantity] + float(tier.total_price))

    return float(dp[quantity] if dp[quantity] != float("inf") else quantity * base_price)


def is_controller_pricing_supported(console_name: str) -> bool:
    value = str(console_name or "").strip().lower()
    return ("ps" in value) or ("xbox" in value)


def _resolve_console_group(console_name: str) -> str:
    value = str(console_name or "").strip().lower()
    if "ps" in value:
        return "ps"
    if "xbox" in value:
        return "xbox"
    if "vr" in value:
        return "vr"
    if "pc" in value:
        return "pc"
    return "unknown"


def _load_squad_pricing_policy(vendor_id: int):
    policy = {
        group: {int(players): float(discount) for players, discount in values.items()}
        for group, values in DEFAULT_SQUAD_PRICING_POLICY.items()
    }
    rows = (
        SquadPricingRule.query
        .filter_by(vendor_id=vendor_id, is_active=True)
        .all()
    )
    if not rows:
        return policy

    for group in list(policy.keys()):
        policy[group] = {}

    for row in rows:
        group = str(row.console_group or "").strip().lower()
        if group != "pc":
            continue
        max_rule_players = int(SQUAD_PLATFORM_RULES["pc"]["max_players"])
        if int(row.player_count) < 2 or int(row.player_count) > max_rule_players:
            continue
        policy[group][int(row.player_count)] = float(row.discount_percent or 0)

    if not policy.get("pc"):
        defaults = DEFAULT_SQUAD_PRICING_POLICY["pc"]
        policy["pc"] = {int(k): float(v) for k, v in defaults.items()}

    return policy


def _max_players_for_console(console_name: str, policy: dict = None) -> int:
    group = _resolve_console_group(console_name)
    rules = SQUAD_PLATFORM_RULES.get(group)
    if not rules:
        return 1
    return int(rules.get("max_players", 1))


def _resolve_squad_discount_percent(console_name: str, player_count: int, policy: dict = None) -> float:
    if player_count <= 1:
        return 0.0
    group = _resolve_console_group(console_name)
    if group != "pc":
        return 0.0
    source = policy or DEFAULT_SQUAD_PRICING_POLICY
    grid = source.get(group, {})
    if not grid:
        return 0.0
    capped_players = max(2, min(int(player_count), max(grid.keys())))
    return float(grid.get(capped_players, 0.0))


def _resolve_squad_pricing_mode(console_name: str) -> str:
    group = _resolve_console_group(console_name)
    return str(SQUAD_PLATFORM_RULES.get(group, {}).get("pricing_mode", "solo_only"))


def _safe_decode_jwt_claims(token: str):
    """
    Decode JWT payload without signature verification for telemetry/audit tagging.
    Never use this for auth decisions.
    """
    try:
        parts = (token or "").split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)  # add base64 padding
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_transaction_actor(request_obj):
    """
    Resolve source + staff attribution for transaction audit logs.
    """
    source_header = (request_obj.headers.get("X-Client-Source") or "").strip().lower()
    source_channel = source_header if source_header in {"app", "dashboard"} else "app"

    actor = {
        "source_channel": source_channel,
        "staff_id": None,
        "staff_name": None,
        "staff_role": None,
    }

    auth_header = request_obj.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        claims = _safe_decode_jwt_claims(token)

        staff_claim = claims.get("staff")
        if isinstance(staff_claim, dict):
            actor["staff_id"] = str(staff_claim.get("id") or staff_claim.get("staff_id") or "")
            actor["staff_name"] = staff_claim.get("name")
            actor["staff_role"] = staff_claim.get("role")
            actor["source_channel"] = "dashboard"

    return actor


def _coerce_date_value(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    if isinstance(raw_value, str):
        text_value = raw_value.strip()
        if not text_value:
            return None
        try:
            if "T" in text_value:
                return datetime.fromisoformat(text_value).date()
            return datetime.strptime(text_value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def resolve_booking_booked_date(booking, fallback_date=None):
    if not booking:
        return _coerce_date_value(fallback_date) or datetime.utcnow().date()

    direct_value = getattr(booking, "booked_date", None)
    resolved = _coerce_date_value(direct_value)
    if resolved:
        return resolved

    details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
    resolved = _coerce_date_value(details.get("booked_date") or details.get("book_date"))
    if resolved:
        return resolved

    if booking.created_at:
        return booking.created_at.date()

    return _coerce_date_value(fallback_date) or datetime.utcnow().date()


def normalize_payment_use_case(payment_type: str, source_channel: str) -> str:
    pt = str(payment_type or "").strip().lower()
    if pt in {"monthly_credit", "credit", "month_end"}:
        return "monthly_credit"
    if pt == "cash":
        return "pay_at_cafe" if source_channel == "app" else "cash"
    if pt == "upi":
        return "upi"
    if pt in {"card", "cards", "credit_card", "debit", "debit_card"}:
        return "card"
    if pt in {"pass", "date_pass", "hour_pass"}:
        return "pass"
    if pt in {"wallet", "hash_wallet"}:
        return "hash_wallet"
    if pt in {"gateway", "payment_gateway", "paid", "online"}:
        return "payment_gateway"
    return pt or "unknown"


def validate_monthly_credit_capacity(credit_account, requested_charge: float):
    requested_charge = max(float(requested_charge or 0.0), 0.0)
    outstanding_amount = float(getattr(credit_account, "outstanding_amount", 0.0) or 0.0)
    credit_limit = float(getattr(credit_account, "credit_limit", 0.0) or 0.0)
    available_credit = max(credit_limit - outstanding_amount, 0.0)

    if requested_charge > available_credit:
        return {
            "success": False,
            "message": "Monthly credit limit exceeded for this customer.",
            "credit_limit": round(credit_limit, 2),
            "current_outstanding": round(outstanding_amount, 2),
            "requested_charge": round(requested_charge, 2),
            "available_credit": round(available_credit, 2),
        }
    return None


def resolve_settlement_status(payment_use_case: str) -> str:
    if payment_use_case == "pay_at_cafe":
        return "pending"
    if payment_use_case == "monthly_credit":
        return "pending"
    if payment_use_case in {"cash", "upi", "card", "payment_gateway", "hash_wallet", "pass"}:
        return "completed"
    return "pending"


def _resolve_or_create_squad_member_user(member_name: str, member_phone: str):
    phone = str(member_phone or "").strip()
    name = str(member_name or "").strip()
    if not phone:
        return None

    contact_match = ContactInfo.query.filter(
        and_(
            ContactInfo.parent_type == "user",
            ContactInfo.phone == phone,
        )
    ).first()
    if contact_match and contact_match.parent_id:
        return int(contact_match.parent_id)

    safe_phone = "".join(ch for ch in phone if ch.isdigit())[-10:] or str(random.randint(1000000000, 9999999999))
    base_email = f"squad+{safe_phone}@hash.local"
    email_candidate = base_email
    suffix = 1
    while ContactInfo.query.filter(
        and_(
            ContactInfo.parent_type == "user",
            ContactInfo.email == email_candidate,
        )
    ).first():
        email_candidate = f"squad+{safe_phone}.{suffix}@hash.local"
        suffix += 1

    username_base = "".join(ch for ch in (name.lower() or "player") if ch.isalnum())[:16] or "player"
    game_username = f"{username_base}_{random.randint(1000, 9999)}"
    while User.query.filter(User.game_username == game_username).first():
        game_username = f"{username_base}_{random.randint(1000, 9999)}"

    new_user = User(
        fid=generate_fid(),
        avatar_path="Not defined",
        name=name or f"Player {safe_phone[-4:]}",
        game_username=game_username,
        parent_type="user",
    )
    new_contact = ContactInfo(
        phone=phone,
        email=email_candidate,
        parent_type="user",
    )
    new_user.contact_info = new_contact
    db.session.add(new_user)
    db.session.flush()
    return int(new_user.id)


def _normalize_squad_booking_payload(
    squad_payload,
    console_name: str,
    vendor_policy: dict = None,
):
    if not isinstance(squad_payload, dict):
        raise ValueError("squad_details must be an object")

    squad_enabled = bool(squad_payload.get("enabled", False))
    try:
        squad_player_count = int(
            squad_payload.get("player_count")
            or squad_payload.get("playerCount")
            or 1
        )
    except (TypeError, ValueError):
        raise ValueError("squad_details.player_count must be a valid integer")

    try:
        suggested_extra_controller_qty = int(
            squad_payload.get("suggested_extra_controller_qty")
            or squad_payload.get("suggestedExtraControllerQty")
            or 0
        )
    except (TypeError, ValueError):
        raise ValueError("squad_details.suggested_extra_controller_qty must be a valid integer")

    raw_members = squad_payload.get("members", [])
    if raw_members is None:
        raw_members = []
    if not isinstance(raw_members, list):
        raise ValueError("squad_details.members must be an array")

    normalized_members = []
    for member in raw_members[:20]:
        if not isinstance(member, dict):
            continue
        member_name = str(member.get("name", "")).strip()
        member_phone = str(member.get("phone", "")).strip()
        if not member_name and not member_phone:
            continue
        if not member_name or not member_phone:
            raise ValueError("Each squad member must include both name and phone")
        normalized_members.append({
            "name": member_name[:120],
            "phone": member_phone[:32],
        })

    normalized_details = {
        "enabled": squad_enabled,
        "player_count": max(squad_player_count, 1),
        "suggested_extra_controller_qty": max(suggested_extra_controller_qty, 0),
        "members": normalized_members,
    }

    if not squad_enabled:
        return normalized_details

    console_group = _resolve_console_group(console_name or "")
    group_rules = SQUAD_PLATFORM_RULES.get(
        console_group,
        {"enabled": False, "max_players": 1, "pricing_mode": "solo_only"},
    )
    max_players = int(group_rules.get("max_players", 1))
    pricing_mode = str(group_rules.get("pricing_mode", "solo_only"))

    if not bool(group_rules.get("enabled")):
        raise ValueError(f"Squad booking is not supported for {console_name}")
    if normalized_details["player_count"] < 2:
        raise ValueError("Squad booking requires at least 2 players")
    if normalized_details["player_count"] > max_players:
        raise ValueError(f"Squad player count cannot exceed {max_players} for this console type")

    discount_pct = _resolve_squad_discount_percent(
        console_name or "",
        normalized_details["player_count"],
        policy=vendor_policy,
    )
    normalized_details["console_group"] = console_group
    normalized_details["max_players_for_console"] = max_players
    normalized_details["pricing_mode"] = pricing_mode
    normalized_details["discount_percent"] = discount_pct

    if pricing_mode == "controller_pricing":
        normalized_details["suggested_extra_controller_qty"] = max(
            normalized_details["suggested_extra_controller_qty"],
            normalized_details["player_count"] - 1,
        )

    return normalized_details


def _build_squad_member_bindings(captain_user, captain_name: str, captain_phone: str, normalized_squad_details: dict):
    if not normalized_squad_details or not bool(normalized_squad_details.get("enabled")):
        return []

    bindings = [{
        "member_user_id": int(captain_user.id),
        "member_position": 1,
        "is_captain": True,
        "name_snapshot": str(captain_name or getattr(captain_user, "name", "") or "Captain").strip()[:255] or "Captain",
        "phone_snapshot": str(captain_phone or "").strip()[:50],
    }]

    phone_binding_cache = {}
    for idx, member in enumerate(normalized_squad_details.get("members", []), start=2):
        member_phone = str(member.get("phone", "")).strip()[:50]
        member_name = str(member.get("name", "")).strip()[:255]
        resolved_user_id = None
        if member_phone:
            if member_phone in phone_binding_cache:
                resolved_user_id = phone_binding_cache[member_phone]
            else:
                resolved_user_id = _resolve_or_create_squad_member_user(member_name, member_phone)
                phone_binding_cache[member_phone] = resolved_user_id
        bindings.append({
            "member_user_id": resolved_user_id,
            "member_position": idx,
            "is_captain": False,
            "name_snapshot": member_name,
            "phone_snapshot": member_phone,
        })

    normalized_squad_details["member_user_ids"] = [
        int(binding["member_user_id"])
        for binding in bindings
        if binding.get("member_user_id")
    ]
    return bindings


def _is_slot_live_now_ist(slot_date, start_time, end_time) -> bool:
    if not slot_date or not start_time or not end_time:
        return False
    now_ist = datetime.now(IST).replace(tzinfo=None)
    if slot_date != now_ist.date():
        return False
    start_dt = datetime.combine(slot_date, start_time)
    end_dt = datetime.combine(slot_date, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt <= now_ist <= end_dt


def _reserve_specific_console(vendor_id: int, game_id: int, console_id: int):
    table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
    row = db.session.execute(
        text(f"""
            WITH candidate AS (
                SELECT console_id
                FROM {table_name}
                WHERE vendor_id = :vendor_id
                  AND game_id = :game_id
                  AND console_id = :console_id
                  AND is_available = TRUE
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE {table_name} c
            SET is_available = FALSE
            FROM candidate
            WHERE c.vendor_id = :vendor_id
              AND c.console_id = candidate.console_id
            RETURNING c.console_id
        """),
        {"vendor_id": vendor_id, "game_id": game_id, "console_id": console_id},
    ).fetchone()
    return int(row[0]) if row else None


def _reserve_any_console(vendor_id: int, game_id: int):
    table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
    row = db.session.execute(
        text(f"""
            WITH candidate AS (
                SELECT console_id
                FROM {table_name}
                WHERE vendor_id = :vendor_id
                  AND game_id = :game_id
                  AND is_available = TRUE
                ORDER BY console_id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE {table_name} c
            SET is_available = FALSE
            FROM candidate
            WHERE c.vendor_id = :vendor_id
              AND c.console_id = candidate.console_id
            RETURNING c.console_id
        """),
        {"vendor_id": vendor_id, "game_id": game_id},
    ).fetchone()
    return int(row[0]) if row else None


def _reserve_multiple_consoles(vendor_id: int, game_id: int, quantity: int):
    if int(quantity or 0) <= 0:
        return []
    table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
    rows = db.session.execute(
        text(f"""
            WITH candidate AS (
                SELECT console_id
                FROM {table_name}
                WHERE vendor_id = :vendor_id
                  AND game_id = :game_id
                  AND is_available = TRUE
                ORDER BY console_id
                LIMIT :quantity
                FOR UPDATE SKIP LOCKED
            )
            UPDATE {table_name} c
            SET is_available = FALSE
            FROM candidate
            WHERE c.vendor_id = :vendor_id
              AND c.console_id = candidate.console_id
            RETURNING c.console_id
        """),
        {"vendor_id": vendor_id, "game_id": game_id, "quantity": int(quantity)},
    ).fetchall()

    reserved_ids = []
    seen = set()
    for row in rows or []:
        cid = int(row[0])
        if cid in seen:
            continue
        seen.add(cid)
        reserved_ids.append(cid)
    return reserved_ids


def _release_reserved_consoles(vendor_id: int, console_ids):
    cleaned_ids = [int(cid) for cid in (console_ids or []) if cid is not None]
    if not cleaned_ids:
        return
    table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
    db.session.execute(
        text(f"""
            UPDATE {table_name}
            SET is_available = TRUE
            WHERE vendor_id = :vendor_id
              AND console_id = ANY(:console_ids)
        """),
        {"vendor_id": vendor_id, "console_ids": cleaned_ids},
    )


@booking_blueprint.route('/vendor/<int:vendor_id>/squad-pricing-policy', methods=['GET'])
def get_squad_pricing_policy(vendor_id):
    """
    Return current squad pricing matrix.
    This is a backend source-of-truth policy for frontend previews.
    """
    try:
        available_games = (
            AvailableGame.query
            .filter(AvailableGame.vendor_id == vendor_id)
            .all()
        )
        console_groups = sorted({
            _resolve_console_group(game.game_name or "")
            for game in available_games
        })
        if not console_groups:
            console_groups = sorted(DEFAULT_SQUAD_PRICING_POLICY.keys())
        policy = _load_squad_pricing_policy(vendor_id)

        return jsonify({
            "success": True,
            "policy": {
                group: {str(k): float(v) for k, v in values.items()}
                for group, values in policy.items()
            },
            "available_console_groups": console_groups,
            "platform_rules": SQUAD_PLATFORM_RULES,
            "rule_engine_scope": ["pc"],
            "discount_basis": "slot_base_only",
            "note": "Discount applies per slot on console base amount only. Meals/controllers are excluded."
        }), 200
    except Exception as e:
        current_app.logger.error(f"Failed to fetch squad pricing policy: {str(e)}")
        return jsonify({"success": False, "message": "Failed to fetch squad pricing policy"}), 500


@booking_blueprint.route('/bookings/pricing-preview', methods=['POST'])
def booking_pricing_preview():
    try:
        data = request.get_json(force=True) or {}

        vendor_id = data.get("vendor_id")
        game_id = data.get("game_id")
        console_id = data.get("console_id") or data.get("consoleId")
        console_type = data.get("console_type") or data.get("consoleType")
        book_date_str = data.get("book_date")
        raw_slot_ids = data.get("slot_id") or data.get("slot_ids") or []
        raw_selected_slots = data.get("selected_slots") or data.get("selectedSlots") or []
        slot_count = data.get("slot_count") or data.get("slotCount")
        squad_payload = data.get("squad_details") or data.get("squadDetails") or {}
        selected_meals = data.get("selected_meals") or data.get("selectedMeals") or []
        waive_off_total = float(data.get("waive_off_amount") or data.get("waiveOffAmount") or 0.0)

        if not vendor_id or not book_date_str or (not raw_slot_ids and not raw_selected_slots and not slot_count):
            return jsonify({
                "success": False,
                "message": "vendor_id, book_date and one of slot_id, selected_slots or slot_count are required"
            }), 400

        try:
            vendor_id = int(vendor_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "vendor_id must be a valid integer"}), 400

        slot_ids = []
        if raw_slot_ids:
            if isinstance(raw_slot_ids, int):
                slot_ids = [raw_slot_ids]
            elif isinstance(raw_slot_ids, list):
                slot_ids = raw_slot_ids
            else:
                return jsonify({"success": False, "message": "slot_id must be a list or integer"}), 400

            try:
                slot_ids = [int(slot_id) for slot_id in slot_ids]
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "slot_id contains invalid values"}), 400

        try:
            if "T" in str(book_date_str):
                book_date = datetime.fromisoformat(str(book_date_str)).date()
            else:
                book_date = datetime.strptime(str(book_date_str), "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"success": False, "message": "Invalid book_date format"}), 400

        available_game = _resolve_available_game_for_vendor(
            vendor_id=vendor_id,
            console_type=console_type,
            console_id=console_id,
            game_id=game_id,
        )
        if not available_game:
            return jsonify({"success": False, "message": "Game not found for this vendor"}), 404

        vendor_squad_policy = _load_squad_pricing_policy(vendor_id)
        try:
            normalized_squad_details = _normalize_squad_booking_payload(
                squad_payload,
                available_game.game_name or "",
                vendor_policy=vendor_squad_policy,
            )
        except ValueError as squad_error:
            return jsonify({"success": False, "message": str(squad_error)}), 400

        squad_enabled = bool(normalized_squad_details.get("enabled"))
        console_group = str(
            normalized_squad_details.get("console_group") or _resolve_console_group(available_game.game_name or "")
        ).strip().lower()
        is_pc_squad = bool(squad_enabled and console_group == "pc")
        squad_player_count = int(normalized_squad_details.get("player_count") or normalized_squad_details.get("playerCount") or 1)
        slot_units_required = squad_player_count if is_pc_squad else 1
        squad_discount_percent = float(normalized_squad_details.get("discount_percent") or 0.0)

        def _parse_preview_time(value):
            if value is None:
                return None
            value = str(value).strip()
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
            return None

        slot_entries = []
        if slot_ids:
            slot_rows = Slot.query.filter(Slot.id.in_(slot_ids)).all()
            slot_map = {int(slot.id): slot for slot in slot_rows}
            missing_slots = [slot_id for slot_id in slot_ids if slot_id not in slot_map]
            if missing_slots:
                return jsonify({
                    "success": False,
                    "message": "One or more slots were not found",
                    "missing_slot_ids": missing_slots,
                }), 404
            for slot_id in slot_ids:
                slot_entries.append({
                    "slot_id": int(slot_id),
                    "slot_obj": slot_map[slot_id],
                    "availability_check": True,
                })
        elif raw_selected_slots:
            if not isinstance(raw_selected_slots, list):
                return jsonify({"success": False, "message": "selected_slots must be an array"}), 400

            fallback_slots = Slot.query.filter(Slot.gaming_type_id == available_game.id).all()
            for idx, raw_slot in enumerate(raw_selected_slots, start=1):
                start_time = None
                end_time = None
                slot_id = None
                matched_slot = None

                if isinstance(raw_slot, dict):
                    slot_id = raw_slot.get("slot_id") or raw_slot.get("slotId")
                    start_time = _parse_preview_time(raw_slot.get("start_time") or raw_slot.get("startTime"))
                    end_time = _parse_preview_time(raw_slot.get("end_time") or raw_slot.get("endTime"))
                elif isinstance(raw_slot, str):
                    normalized = raw_slot.strip()
                    if "-" in normalized:
                        parts = [part.strip() for part in normalized.split("-", 1)]
                        start_time = _parse_preview_time(parts[0])
                        end_time = _parse_preview_time(parts[1])
                    else:
                        start_time = _parse_preview_time(normalized)
                else:
                    return jsonify({"success": False, "message": "selected_slots contains invalid entries"}), 400

                if slot_id is not None:
                    try:
                        slot_id = int(slot_id)
                    except (TypeError, ValueError):
                        return jsonify({"success": False, "message": "selected_slots.slot_id must be a valid integer"}), 400
                    matched_slot = Slot.query.filter_by(id=slot_id, gaming_type_id=available_game.id).first()
                    if not matched_slot:
                        return jsonify({"success": False, "message": f"Slot {slot_id} not found for selected console"}), 404
                    if start_time is None:
                        start_time = matched_slot.start_time
                    if end_time is None:
                        end_time = matched_slot.end_time
                else:
                    for candidate in fallback_slots:
                        if start_time is not None and candidate.start_time != start_time:
                            continue
                        if end_time is not None and candidate.end_time != end_time:
                            continue
                        matched_slot = candidate
                        break

                if start_time is None and matched_slot is not None:
                    start_time = matched_slot.start_time
                if end_time is None and matched_slot is not None:
                    end_time = matched_slot.end_time
                if start_time is None or end_time is None:
                    return jsonify({
                        "success": False,
                        "message": "Each selected slot must include start_time and end_time when slot_id is not provided"
                    }), 400

                slot_entries.append({
                    "slot_id": int(matched_slot.id) if matched_slot else None,
                    "slot_obj": matched_slot or type("PreviewSlot", (), {
                        "id": None,
                        "start_time": start_time,
                        "end_time": end_time
                    })(),
                    "availability_check": bool(matched_slot),
                })
        else:
            try:
                slot_count = int(slot_count or 0)
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "slot_count must be a valid integer"}), 400
            if slot_count <= 0:
                return jsonify({"success": False, "message": "slot_count must be greater than 0"}), 400

            first_slot = (
                Slot.query
                .filter(Slot.gaming_type_id == available_game.id)
                .order_by(Slot.start_time.asc())
                .first()
            )
            if not first_slot:
                return jsonify({"success": False, "message": "No slots configured for this console"}), 404

            for index in range(slot_count):
                slot_entries.append({
                    "slot_id": None,
                    "slot_obj": first_slot,
                    "availability_check": False,
                    "sequence": index + 1,
                })

        total_meals_cost = 0.0
        meal_breakdown = []
        for meal in selected_meals:
            menu_item_id = meal.get("menu_item_id") or meal.get("item_id")
            quantity = meal.get("quantity", 1)
            try:
                quantity = int(quantity or 1)
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "Meal quantity must be a valid integer"}), 400
            if not menu_item_id or quantity <= 0:
                return jsonify({"success": False, "message": "Invalid meal data provided"}), 400

            menu_item = db.session.query(ExtraServiceMenu).join(
                ExtraServiceCategory
            ).filter(
                ExtraServiceMenu.id == int(menu_item_id),
                ExtraServiceCategory.vendor_id == vendor_id,
                ExtraServiceMenu.is_active == True,
                ExtraServiceCategory.is_active == True
            ).first()

            if not menu_item:
                return jsonify({
                    "success": False,
                    "message": f"Invalid or inactive menu item {menu_item_id} for this vendor"
                }), 400

            item_total = float(menu_item.price or 0.0) * quantity
            total_meals_cost += item_total
            meal_breakdown.append({
                "menu_item_id": int(menu_item.id),
                "name": menu_item.name,
                "quantity": quantity,
                "unit_price": float(menu_item.price or 0.0),
                "total_price": round(item_total, 2),
            })

        try:
            requested_extra_controller_qty = int(
                data.get("extra_controller_qty")
                or data.get("extraControllerQty")
                or 0
            )
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "extra_controller_qty must be a valid integer"}), 400
        if requested_extra_controller_qty < 0:
            return jsonify({"success": False, "message": "extra_controller_qty cannot be negative"}), 400

        if squad_enabled and console_group in {"ps", "xbox"}:
            requested_extra_controller_qty = max(requested_extra_controller_qty, squad_player_count - 1)
        elif not is_controller_pricing_supported(available_game.game_name):
            requested_extra_controller_qty = 0

        extra_controller_fare = 0.0
        if requested_extra_controller_qty > 0:
            computed_controller_fare = calculate_extra_controller_fare(
                vendor_id=vendor_id,
                available_game_id=available_game.id,
                quantity=requested_extra_controller_qty,
            )
            if computed_controller_fare is None:
                return jsonify({
                    "success": False,
                    "message": "Controller pricing is not configured for this console type."
                }), 400
            extra_controller_fare = float(computed_controller_fare or 0.0)

        slot_breakdown = []
        total_base_before_discount = 0.0
        total_discount = 0.0

        for entry in slot_entries:
            slot_obj = entry["slot_obj"]
            slot_id = entry.get("slot_id")
            effective_price = get_effective_price_for_schedule(vendor_id, available_game, book_date, slot_obj)
            slot_base_price = float(effective_price or 0.0) * (squad_player_count if is_pc_squad else 1)
            slot_discount = (
                (slot_base_price * squad_discount_percent / 100.0)
                if is_pc_squad and str(normalized_squad_details.get("pricing_mode") or "") == "squad_discount"
                else 0.0
            )

            available_slot = None
            slot_is_available = None
            if entry.get("availability_check") and slot_id is not None:
                availability_row = db.session.execute(
                    text(f"""
                        SELECT available_slot, is_available
                        FROM VENDOR_{vendor_id}_SLOT
                        WHERE slot_id = :slot_id AND date = :book_date
                    """),
                    {"slot_id": slot_id, "book_date": book_date}
                ).fetchone()

                available_slot = int(availability_row[0]) if availability_row and availability_row[0] is not None else None
                slot_is_available = bool(availability_row[1]) if availability_row and availability_row[1] is not None else False

            total_base_before_discount += slot_base_price
            total_discount += slot_discount
            slot_breakdown.append({
                "slot_id": int(slot_id) if slot_id is not None else None,
                "start_time": str(slot_obj.start_time),
                "end_time": str(slot_obj.end_time),
                "slot_unit_price": round(float(effective_price or 0.0), 2),
                "slot_base_price": round(float(slot_base_price or 0.0), 2),
                "slot_discount_amount": round(float(slot_discount or 0.0), 2),
                "slot_final_amount": round(max(float(slot_base_price or 0.0) - float(slot_discount or 0.0), 0.0), 2),
                "available_slot": available_slot,
                "slot_units_required": int(slot_units_required),
                "can_book": (
                    bool(available_slot is not None and available_slot >= slot_units_required and slot_is_available)
                    if entry.get("availability_check")
                    else None
                ),
            })

        final_amount = max(
            float(total_base_before_discount)
            - float(total_discount)
            - float(waive_off_total or 0.0)
            + float(total_meals_cost or 0.0)
            + float(extra_controller_fare or 0.0),
            0.0
        )

        if squad_enabled:
            normalized_squad_details["discount_per_slot"] = round(
                (slot_breakdown[0]["slot_discount_amount"] if slot_breakdown else 0.0), 2
            )
            normalized_squad_details["total_discount"] = round(float(total_discount or 0.0), 2)
            normalized_squad_details["slot_base_multiplier"] = int(squad_player_count if is_pc_squad else 1)
            normalized_squad_details["applied_extra_controller_qty"] = int(requested_extra_controller_qty)

        return jsonify({
            "success": True,
            "vendor_id": vendor_id,
            "matched_game_id": int(available_game.id),
            "matched_game_name": available_game.game_name,
            "book_date": str(book_date),
            "slot_breakdown": slot_breakdown,
            "squad_details": normalized_squad_details if squad_enabled else {
                "enabled": False,
                "player_count": 1,
                "suggested_extra_controller_qty": 0,
                "members": [],
            },
            "pricing_engine": {
                "slot_base_total": round(float(total_base_before_discount or 0.0), 2),
                "squad_discount_percent": round(float(squad_discount_percent or 0.0), 2),
                "squad_discount_amount": round(float(total_discount or 0.0), 2),
                "manual_waive_off_amount": round(float(waive_off_total or 0.0), 2),
                "meals_total": round(float(total_meals_cost or 0.0), 2),
                "extra_controller_qty": int(requested_extra_controller_qty),
                "extra_controller_total": round(float(extra_controller_fare or 0.0), 2),
                "final_amount": round(float(final_amount or 0.0), 2),
            },
            "meal_breakdown": meal_breakdown,
        }), 200

    except Exception as e:
        current_app.logger.exception("Failed to build booking pricing preview")
        return jsonify({
            "success": False,
            "message": "Failed to build booking pricing preview",
            "error": str(e),
        }), 500


@booking_blueprint.route('/bookings/pricing-estimate', methods=['GET'])
def booking_pricing_estimate():
    try:
        payload = request.get_json(silent=True) or {}
        query = request.args

        vendor_id = query.get("vendor_id", payload.get("vendor_id"))
        game_id = query.get("game_id", payload.get("game_id"))
        console_type = query.get("consoleType") or query.get("console_type") or payload.get("consoleType") or payload.get("console_type")
        squad_payload = payload.get("squadDetails") or payload.get("squad_details") or {}
        if not squad_payload:
            squad_enabled_raw = query.get("squadEnabled", query.get("enabled", payload.get("squadEnabled", payload.get("enabled"))))
            player_count_raw = query.get("playerCount", query.get("player_count", payload.get("playerCount", payload.get("player_count"))))
            squad_payload = {
                "enabled": str(squad_enabled_raw).lower() == "true" if squad_enabled_raw is not None else False,
                "player_count": player_count_raw or 1,
            }

        if not vendor_id:
            return jsonify({"success": False, "message": "vendor_id is required"}), 400

        try:
            vendor_id = int(vendor_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "vendor_id must be a valid integer"}), 400

        if game_id is not None:
            try:
                game_id = int(game_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "game_id must be a valid integer"}), 400

        available_game = _resolve_available_game_for_vendor(
            vendor_id=vendor_id,
            console_type=console_type,
            game_id=game_id,
        )
        if not available_game:
            return jsonify({"success": False, "message": "Game not found for this vendor"}), 404

        vendor_squad_policy = _load_squad_pricing_policy(vendor_id)
        try:
            normalized_squad_details = _normalize_squad_booking_payload(
                squad_payload,
                available_game.game_name or "",
                vendor_policy=vendor_squad_policy,
            )
        except ValueError as squad_error:
            return jsonify({"success": False, "message": str(squad_error)}), 400

        squad_enabled = bool(normalized_squad_details.get("enabled"))
        console_group = str(
            normalized_squad_details.get("console_group") or _resolve_console_group(available_game.game_name or "")
        ).strip().lower()
        is_pc_squad = bool(squad_enabled and console_group == "pc")
        squad_player_count = int(normalized_squad_details.get("player_count") or normalized_squad_details.get("playerCount") or 1)
        effective_price = get_effective_price(vendor_id, available_game)

        slot_unit_price = float(effective_price or 0.0)
        slot_base_price = slot_unit_price * (squad_player_count if is_pc_squad else 1)
        squad_discount_percent = float(normalized_squad_details.get("discount_percent") or 0.0)
        squad_discount_amount = (
            (slot_base_price * squad_discount_percent / 100.0)
            if is_pc_squad and str(normalized_squad_details.get("pricing_mode") or "") == "squad_discount"
            else 0.0
        )

        extra_controller_qty = 0
        extra_controller_fare = 0.0
        if squad_enabled and console_group in {"ps", "xbox"}:
            extra_controller_qty = max(0, squad_player_count - 1)
            if extra_controller_qty > 0:
                computed_controller_fare = calculate_extra_controller_fare(
                    vendor_id=vendor_id,
                    available_game_id=available_game.id,
                    quantity=extra_controller_qty,
                )
                if computed_controller_fare is None:
                    return jsonify({
                        "success": False,
                        "message": "Controller pricing is not configured for this console type."
                    }), 400
                extra_controller_fare = float(computed_controller_fare or 0.0)

        estimated_final_amount = max((slot_base_price - squad_discount_amount) + extra_controller_fare, 0.0)

        if squad_enabled:
            normalized_squad_details["discount_per_slot"] = round(float(squad_discount_amount or 0.0), 2)
            normalized_squad_details["slot_base_multiplier"] = int(squad_player_count if is_pc_squad else 1)
            normalized_squad_details["applied_extra_controller_qty"] = int(extra_controller_qty)

        return jsonify({
            "success": True,
            "vendor_id": vendor_id,
            "matched_game_id": int(available_game.id),
            "matched_game_name": available_game.game_name,
            "estimate_scope": "per_slot",
            "price_basis": "current_effective_price",
            "squad_details": normalized_squad_details if squad_enabled else {
                "enabled": False,
                "player_count": 1,
                "suggested_extra_controller_qty": 0,
                "members": [],
            },
            "pricing_engine": {
                "slot_unit_price": round(slot_unit_price, 2),
                "slot_base_total": round(slot_base_price, 2),
                "squad_discount_percent": round(squad_discount_percent, 2),
                "squad_discount_amount": round(squad_discount_amount, 2),
                "extra_controller_qty": int(extra_controller_qty),
                "extra_controller_total": round(extra_controller_fare, 2),
                "estimated_final_amount": round(estimated_final_amount, 2),
            },
        }), 200

    except Exception as e:
        current_app.logger.exception("Failed to build booking pricing estimate")
        return jsonify({
            "success": False,
            "message": "Failed to build booking pricing estimate",
            "error": str(e),
        }), 500


def calculate_slot_minutes(slot_obj: Slot) -> int:
    if not slot_obj or not slot_obj.start_time or not slot_obj.end_time:
        return 0
    start_dt = datetime.combine(datetime.utcnow().date(), slot_obj.start_time)
    end_dt = datetime.combine(datetime.utcnow().date(), slot_obj.end_time)
    mins = int((end_dt - start_dt).total_seconds() / 60)
    return max(mins, 0)


def calculate_gst_breakdown(vendor_id: int, amount: float):
    amount = float(amount or 0)
    zero = {
        "taxable_amount": amount,
        "gst_rate": 0.0,
        "cgst_amount": 0.0,
        "sgst_amount": 0.0,
        "igst_amount": 0.0,
        "total_with_tax": amount,
    }
    if amount <= 0:
        zero["taxable_amount"] = 0.0
        zero["total_with_tax"] = 0.0
        return zero

    profile = VendorTaxProfile.query.filter_by(vendor_id=vendor_id).first()
    if not profile or not profile.gst_registered or not profile.gst_enabled:
        return zero

    rate = float(profile.gst_rate or 0)
    if rate <= 0:
        return zero

    if profile.tax_inclusive:
        taxable = round(amount / (1 + rate / 100.0), 2)
        gst_total = round(amount - taxable, 2)
        total = round(amount, 2)
    else:
        taxable = round(amount, 2)
        gst_total = round(taxable * rate / 100.0, 2)
        total = round(taxable + gst_total, 2)

    is_intrastate = bool(
        profile.state_code
        and profile.place_of_supply_state_code
        and str(profile.state_code) == str(profile.place_of_supply_state_code)
    )
    if is_intrastate:
        cgst = round(gst_total / 2.0, 2)
        sgst = round(gst_total - cgst, 2)
        igst = 0.0
    else:
        cgst = 0.0
        sgst = 0.0
        igst = gst_total

    return {
        "taxable_amount": taxable,
        "gst_rate": rate,
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "total_with_tax": total,
    }


def compute_booking_financial_summary(booking_id: int):
    txns = (
        Transaction.query
        .filter(Transaction.booking_id == booking_id)
        .order_by(Transaction.id.asc())
        .all()
    )
    if not txns:
        return {
            "booking_id": booking_id,
            "total_charged": 0.0,
            "amount_paid": 0.0,
            "amount_due": 0.0,
            "line_items": [],
        }

    def _line_total(tx):
        twt = float(tx.total_with_tax or 0)
        return twt if twt > 0 else float(tx.amount or 0)

    total_charged = sum(_line_total(tx) for tx in txns)
    amount_paid = sum(
        _line_total(tx)
        for tx in txns
        if str(tx.settlement_status or "").lower() in {"completed", "done", "settled", "paid"}
    )

    return {
        "booking_id": booking_id,
        "total_charged": round(total_charged, 2),
        "amount_paid": round(amount_paid, 2),
        "amount_due": round(max(total_charged - amount_paid, 0.0), 2),
        "line_items": [
            {
                "transaction_id": tx.id,
                "booking_type": tx.booking_type,
                "payment_use_case": tx.payment_use_case,
                "mode_of_payment": tx.mode_of_payment,
                "settlement_status": tx.settlement_status,
                "line_total": round(_line_total(tx), 2),
                "components": {
                    "base_amount": float(tx.base_amount or 0),
                    "meals_amount": float(tx.meals_amount or 0),
                    "controller_amount": float(tx.controller_amount or 0),
                    "waive_off_amount": float(tx.waive_off_amount or 0),
                    "taxable_amount": float(tx.taxable_amount or 0),
                    "gst_rate": float(tx.gst_rate or 0),
                    "cgst_amount": float(tx.cgst_amount or 0),
                    "sgst_amount": float(tx.sgst_amount or 0),
                    "igst_amount": float(tx.igst_amount or 0),
                    "total_with_tax": float(tx.total_with_tax or 0),
                },
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            } for tx in txns
        ],
    }


def compute_credit_due_date(booked_date, billing_cycle_day: int):
    if not booked_date:
        return None
    day = max(1, min(int(billing_cycle_day or 1), 28))
    year = booked_date.year
    month = booked_date.month
    due_month = month + 1 if booked_date.day > day else month
    due_year = year + (1 if due_month > 12 else 0)
    due_month = 1 if due_month > 12 else due_month
    return datetime(due_year, due_month, day).date()


def _send_booking_mail_async(app, mail_jobs):
    def _runner():
        with app.app_context():
            for kwargs in mail_jobs:
                try:
                    booking_mail(**kwargs)
                except Exception as exc:
                    current_app.logger.exception("booking_mail failed: %s", exc)

    if mail_jobs:
        _ASYNC_EXECUTOR.submit(_runner)


@booking_blueprint.route('/create_order', methods=['POST'])
def create_order():
    data = request.get_json()

    amount = data.get('amount')  # in paisa
    currency = data.get('currency', 'INR')
    receipt = data.get('receipt', f'order_rcpt_{int(time.time())}')

    RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Basic " + base64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
    }

    payload = {
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1
    }

    response = requests.post("https://api.razorpay.com/v1/orders", headers=headers, json=payload)

    if response.ok:
        return jsonify(response.json()), 200

    # For production, just forward the error status and message from Razorpay without exposing internal details
    return jsonify({"error": "Order creation failed"}), response.status_code

@booking_blueprint.route('/capture_payment', methods=['POST'])
def capture_payment():
    data = request.get_json()
    payment_id = data.get('razorpay_payment_id')
    order_id = data.get('razorpay_order_id')
    signature = data.get('razorpay_signature')

    if not payment_id or not order_id or not signature:
        return jsonify({"message": "Missing payment details"}), 400

    RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")

    # Validate signature
    msg = f"{order_id}|{payment_id}"
    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    if generated_signature != signature:
        return jsonify({"message": "Invalid payment signature"}), 400

    # Initialize Razorpay client
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    try:
        # Fetch payment to check status
        payment = razorpay_client.payment.fetch(payment_id)

        if payment['status'] == 'authorized':
            # Capture payment manually if not auto-captured during order creation
            amount = payment['amount']  # amount in paisa
            razorpay_client.payment.capture(payment_id, amount)
            return jsonify({"message": "Payment captured successfully"}), 200

        elif payment["status"] == "captured":
            return jsonify({"message": "Payment already captured"}), 200

        else:
            return jsonify({"message": f"Payment status {payment['status']} - cannot capture."}), 400
    except razorpay.errors.RazorpayError as e:
        current_app.logger.error(f"Razorpay error during capture: {str(e)}")
        return jsonify({"message": "Error capturing payment", "error": str(e)}), 500

@booking_blueprint.route('/bookings', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def create_booking():
    # Correlation id for this request
    g.cid = getattr(g, "cid", None) or str(uuid.uuid4())
    cid = g.cid
    log = current_app.logger

    try:
        user_id = g.auth_user_id
    except Exception:
        user_id = None

    log.info("bookings.post.start cid=%s user_id=%s", cid, user_id)

    data = request.json or {}
    slot_ids = data.get("slot_id")  # list expected
    game_id = data.get("game_id")
    book_date = data.get("book_date")
    is_pay_at_cafe = data.get("is_pay_at_cafe", False)
    squad_payload = data.get("squad_details") or data.get("squadDetails") or {}

    log.info("bookings.post.payload cid=%s slot_ids_len=%s game_id=%s book_date=%s",
             cid, (len(slot_ids) if isinstance(slot_ids, list) else None), game_id, book_date)

    if not slot_ids or not user_id or not game_id or not book_date:
        log.warning("bookings.post.validation_failed cid=%s", cid)
        return jsonify({"message": "slot_id, game_id, user_id, and book_date are required"}), 400

    try:
        socketio = current_app.extensions.get('socketio')
        scheduler = current_app.extensions.get('scheduler')
        log.info("bookings.post.extensions cid=%s has_socketio=%s has_scheduler=%s",
                 cid, bool(socketio), bool(scheduler))

        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()
        if not available_game:
            log.warning("bookings.post.available_game_missing cid=%s game_id=%s", cid, game_id)
            return jsonify({"message": "Game not found"}), 404

        vendor_id = available_game.vendor_id
        vendor_squad_policy = _load_squad_pricing_policy(vendor_id)
        try:
            normalized_squad_details = _normalize_squad_booking_payload(
                squad_payload,
                available_game.game_name or "",
                vendor_policy=vendor_squad_policy,
            )
        except ValueError as squad_error:
            return jsonify({"message": str(squad_error)}), 400
        squad_enabled = bool(normalized_squad_details.get("enabled"))
        if is_pay_at_cafe and squad_enabled and not normalized_squad_details.get("batch_id"):
            normalized_squad_details["batch_id"] = str(uuid.uuid4())
        slot_units = (
            int(normalized_squad_details.get("player_count", 1))
            if squad_enabled and str(normalized_squad_details.get("console_group", "")).lower() == "pc"
            else 1
        )
        log.info("bookings.post.vendor_resolved cid=%s vendor_id=%s", cid, vendor_id)

        booking_mappings = []
        processed = 0
        skipped = 0

        for slot_id in slot_ids:
            processed += 1
            try:
                log.info("bookings.post.slot_check.start cid=%s slot_id=%s", cid, slot_id)

                slot_entry = db.session.execute(text(f"""
                    SELECT available_slot, is_available
                    FROM VENDOR_{vendor_id}_SLOT
                    WHERE slot_id = :slot_id AND date = :book_date
                """), {"slot_id": slot_id, "book_date": book_date}).fetchone()

                log.info("bookings.post.slot_check.result cid=%s slot_id=%s has_entry=%s entry=%s",
                         cid, slot_id, bool(slot_entry), (tuple(slot_entry) if slot_entry else None))

                if slot_entry is None or int(slot_entry[0] or 0) < slot_units or not slot_entry:
                    skipped += 1
                    log.info("bookings.post.slot_skipped cid=%s slot_id=%s reason=%s",
                             cid, slot_id,
                             ("no_entry" if slot_entry is None else ("no_slots" if int(slot_entry[0] or 0) < slot_units else "not_available")))
                    continue

                booking = BookingService.create_booking(
                    slot_id=slot_id,
                    game_id=game_id,
                    user_id=user_id,
                    socketio=socketio,
                    book_date=book_date,
                    is_pay_at_cafe=is_pay_at_cafe,
                    squad_details=normalized_squad_details if squad_enabled else None,
                    slot_units=slot_units,
                )
                db.session.flush()

                log.info("bookings.post.slot_booked cid=%s slot_id=%s booking_id=%s",
                         cid, slot_id, booking.id)

                booking_mappings.append({
                    "slot_id": slot_id,
                    "booking_id": booking.id,
                    "slot_units": slot_units,
                    "squad_details": normalized_squad_details if squad_enabled else {},
                })

                if scheduler:
                    scheduler.enqueue_in(
                        timedelta(seconds=360),
                        BookingService.release_slot,
                        slot_id,
                        booking.id,
                        book_date
                    )
                    log.info("bookings.post.release_scheduled cid=%s slot_id=%s booking_id=%s delay_sec=%s",
                             cid, slot_id, booking.id, 360)

            except Exception as loop_err:
                # Do not abort the entire batch; record and continue
                log.exception("bookings.post.slot_error cid=%s slot_id=%s error=%s", cid, slot_id, loop_err)
                continue

        try:
            db.session.commit()
            log.info("bookings.post.db_committed cid=%s bookings_count=%s skipped=%s processed=%s",
                     cid, len(booking_mappings), skipped, processed)
        except Exception as commit_err:
            db.session.rollback()
            log.exception("bookings.post.db_commit_failed cid=%s error=%s", cid, commit_err)
            return jsonify({"message": "Failed to freeze slot(s)", "error": "commit_failed"}), 500

        if not booking_mappings:
            log.info("bookings.post.none_booked cid=%s", cid)
            return jsonify({"message": "No slots available for booking"}), 400

        log.info("bookings.post.success cid=%s bookings=%s", cid, booking_mappings)
        return jsonify({
            "message": "Slots frozen",
            "bookings": booking_mappings,
            "squad_details": normalized_squad_details if squad_enabled else {},
        }), 200

    except Exception as e:
        db.session.rollback()
        log.exception("bookings.post.failed cid=%s error=%s", cid, e)
        return jsonify({"message": "Failed to freeze slot(s)", "error": str(e)}), 500

@booking_blueprint.route('/release_slot', methods=['POST'])
def release_slot():
    try:
        data = request.json
        bookings = data.get("bookings")  # Expect a list of {slot_id, booking_id, book_date}

        if not bookings or not isinstance(bookings, list):
            return jsonify({"message": "A list of bookings is required under the 'bookings' key."}), 400

        errors = []
        success_count = 0

        for index, booking in enumerate(bookings):
            slot_id = booking.get("slot_id")
            booking_id = booking.get("booking_id")
            book_date = booking.get("book_date")

            if not slot_id or not booking_id or not book_date:
                errors.append({"index": index, "error": "slot_id, booking_id, and book_date are required"})
                continue

            # Validate date format
            try:
                datetime.strptime(book_date, '%Y-%m-%d')
            except ValueError:
                errors.append({"index": index, "error": "book_date must be in YYYY-MM-DD format"})
                continue

            try:
                BookingService.release_slot(slot_id, booking_id, book_date)
                success_count += 1
            except Exception as e:
                errors.append({"index": index, "error": f"Failed to release slot: {str(e)}"})

        # Keep booking + transaction writes in one DB transaction for consistency.
        db.session.flush()

        response = {"message": f"Processed {success_count} bookings."}
        if errors:
            response["errors"] = errors
            return jsonify(response), 207  # 207 Multi-Status for partial success
        else:
            return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to release slot(s)", "error": str(e)}), 500

@booking_blueprint.route('/generate_payment_link', methods=['POST'])
def generate_payment_link():
    """
    Creates a Razorpay Payment Link and returns the URL.
    Expects JSON: { "amount": 500, "customer_email": "user@example.com", "customer_contact": "9876543210" }
    Amount is expected in rupees.
    """
    data = request.get_json()
    amount_rupees = data.get('amount')
    customer_email = data.get('customer_email')
    customer_contact = data.get('customer_contact')

    if not (amount_rupees and customer_email and customer_contact):
        return jsonify({"message": "Missing required fields!"}), 400

    try:
        amount_paise = int(float(amount_rupees) * 100)
    except Exception:
        return jsonify({"message": "Invalid amount format."}), 400

    RAZORPAY_KEY_ID = current_app.config.get('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET = current_app.config.get('RAZORPAY_KEY_SECRET')
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        return jsonify({'message': 'Server config error.'}), 500

    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    payment_link_data = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": "Payment for your order",
        "customer": {
            "name": "Customer Name",  # Optional, add if you have it
            "contact": customer_contact,
            "email": customer_email
        },
        "notify": {
            "sms": True,
            "email": True
        },
        "reminder_enable": True,
        "callback_method": "get"  # Or "post" if you handle a callback
    }

    try:
        payment_link = client.payment_link.create(payment_link_data)
        return jsonify({
            'payment_link': payment_link['short_url'],
            'id': payment_link['id'],
            'status': payment_link['status']
        })
    except Exception as e:
        return jsonify({'message': 'Error creating payment link', 'error': str(e)}), 500

"""@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    try:
        data = request.get_json(force=True)

        booking_ids         = data.get('booking_id')  # list[int]
        payment_id          = data.get('payment_id')  # Razorpay payment id
        book_date_str       = data.get('book_date')
        voucher_code        = data.get('voucher_code')
        payment_mode        = data.get('payment_mode', "payment_gateway")
        use_pass            = bool(data.get('use_pass', False))
        user_pass_id        = data.get('user_pass_id')  # <-- New param
        extra_services_list = data.get('extra_services', [])  # [{category_id, item_id, quantity}]

        current_app.logger.info(f"Confirm payload: {data}")

        # Basic validation
        if not booking_ids or not book_date_str:
            return jsonify({'message': 'booking_id and book_date are required'}), 400
        if use_pass and not user_pass_id:
            return jsonify({'message': 'user_pass_id is required when use_pass=true'}), 400

        # Parse book_date
        try:
            if 'T' in book_date_str:
                book_date = datetime.fromisoformat(book_date_str).date()
            else:
                book_date = datetime.strptime(book_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"message": "Invalid book_date format"}), 400

        # Setup Razorpay client
        RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
        RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        razorpay_payment_verified = True

        # Verify Razorpay payment if using gateway
        if payment_mode == "payment_gateway":
            if not payment_id:
                return jsonify({"message": "payment_id required for payment_gateway mode"}), 400
            try:
                payment = razorpay_client.payment.fetch(payment_id)
                current_app.logger.info(f"Razorpay payment fetched: {payment}")
                if payment['status'] == 'captured':
                    razorpay_payment_verified = True
                else:
                    return jsonify({"message": "Payment not successful or not captured"}), 400
            except razorpay.errors.RazorpayError as e:
                current_app.logger.error(f"Razorpay verification failed: {str(e)}")
                return jsonify({"message": "Payment verification failed", "error": str(e)}), 400

        # Create an access code for this batch
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        confirmed_ids  = []
        pass_type_name = None
        pass_used_id   = None
        user_id        = None

        for booking_id in booking_ids:
            booking = Booking.query.filter_by(id=booking_id).first()
            if not booking or booking.status == 'confirmed':
                continue

            if user_id is None:
                user_id = booking.user_id

            available_game = AvailableGame.query.filter_by(id=booking.game_id).first()
            vendor         = Vendor.query.filter_by(id=available_game.vendor_id).first() if available_game else None
            slot_obj       = Slot.query.filter_by(id=booking.slot_id).first()
            user           = User.query.filter_by(id=booking.user_id).first()

            if not all([available_game, vendor, slot_obj, user]):
                current_app.logger.warning(f"Booking {booking_id} missing related data")
                continue

            # Pass logic
            active_pass = None
            if use_pass:
                active_pass = UserPass.query.filter_by(
                    id=user_pass_id,
                    user_id=user.id,
                    is_active=True
                ).first()
                if not active_pass or active_pass.valid_to < book_date:
                    return jsonify({"message": "Invalid or expired pass"}), 400
                pass_used_id   = active_pass.id
                pass_type_name = active_pass.cafe_pass.pass_type.name if active_pass.cafe_pass.pass_type else None

            # Calculate slot + extras
            slot_price   = available_game.single_slot_price
            extras_total = 0
            for extra in extra_services_list:
                menu_obj = ExtraServiceMenu.query.filter_by(id=extra.get('item_id'), is_active=True).first()
                if not menu_obj:
                    continue
                extras_total += menu_obj.price * extra.get('quantity', 1)

            # Voucher discount
            voucher             = None
            discount_percentage = 0
            if voucher_code:
                voucher = Voucher.query.filter_by(code=voucher_code, user_id=user.id, is_active=True).first()
                if voucher:
                    discount_percentage = voucher.discount_percentage
                else:
                    return jsonify({'message': 'Invalid or expired voucher'}), 400

            # Amount calculation
            if active_pass:
                discount_amount = slot_price
                amount_payable  = extras_total
            else:
                total_before_discount = slot_price + extras_total
                discount_amount       = int(total_before_discount * discount_percentage / 100)
                amount_payable        = total_before_discount - discount_amount
                pass_used_id          = None
                pass_type_name        = None

            # Payment processing
            if payment_mode == "wallet":
                BookingService.debit_wallet(user.id, booking.id, amount_payable)
                payment_mode_used         = "wallet"
                razorpay_payment_verified = True
            else:
                if amount_payable == 0:
                    razorpay_payment_verified = True
                elif not razorpay_payment_verified:
                    return jsonify({"message": "Payment not verified"}), 400
                payment_mode_used = "payment_gateway"

            # Confirm booking
            booking.status         = 'confirmed'
            booking.updated_at     = datetime.utcnow()
            booking.access_code_id = access_code_entry.id

            # Transaction record (consider adding a nullable pass_id to Transaction for traceability)
            transaction = Transaction(
                booking_id       = booking.id,
                vendor_id        = vendor.id,
                user_id          = user.id,
                user_name        = user.name,
                original_amount  = slot_price + extras_total,
                discounted_amount= discount_amount,
                amount           = amount_payable,
                mode_of_payment  = payment_mode_used,
                booking_date     = datetime.utcnow().date(),
                booked_date      = book_date,
                booking_time     = datetime.utcnow().time(),
                reference_id     = payment_id if payment_mode_used == "payment_gateway" else None
            )
            db.session.add(transaction)
            db.session.flush()

            if payment_id and payment_mode_used == "payment_gateway":
                BookingService.save_payment_transaction_mapping(booking.id, transaction.id, payment_id)

            # Clear and save extras
            BookingExtraService.query.filter_by(booking_id=booking.id).delete()
            for extra in extra_services_list:
                menu_obj = ExtraServiceMenu.query.filter_by(id=extra.get('item_id'), is_active=True).first()
                if not menu_obj:
                    continue

                quantity = extra.get('quantity', 1)
                unit_price = menu_obj.price
                total_price = unit_price * quantity

                booking_extra = BookingExtraService(
                    booking_id=booking.id,
                    menu_item_id=menu_obj.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                db.session.add(booking_extra)

            # Mark voucher as used
            if voucher:
                voucher.is_active = False
                db.session.add(VoucherRedemptionLog(
                    user_id    = user.id,
                    voucher_id = voucher.id,
                    booking_id = booking.id
                ))

            # Reward Hash Coins
            user_hash_coin = UserHashCoin.query.filter_by(user_id=user.id).first()
            if not user_hash_coin:
                user_hash_coin = UserHashCoin(user_id=user.id, hash_coins=0)
                db.session.add(user_hash_coin)
            user_hash_coin.hash_coins += 1000

            # Vendor analytics
            BookingService.insert_into_vendor_dashboard_table(transaction.id, -1)
            BookingService.insert_into_vendor_promo_table(transaction.id, -1)

            # - - After booking.status = 'confirmed' and transaction creation --
            # Gather fields for event payload
            # vendor_id already available via vendor.id
            vendor_id = vendor.id
            booking_id_val = booking.id
            slot_id_val = booking.slot_id
            user_id_val = user.id
            username_val = user.name
            game_id_val = booking.game_id
            game_name_val = available_game.game_name         # from AvailableGame
            date_value = book_date                           # already a date
            slot_price_val = available_game.single_slot_price

            # Pull slot metadata (you already have slot_obj)
            start_time_val = slot_obj.start_time
            end_time_val = slot_obj.end_time
            console_id_val = getattr(slot_obj, "console_id", None)

            # Decide booking_status for confirmed
            # If your UI marks confirmed bookings still as 'upcoming' until start time, keep 'upcoming'.
            # If you prefer to mark as 'current' at confirmation, change accordingly.
            booking_status_dim = "upcoming"

            # Build the exact same message shape used in create flow
            event_payload = build_booking_event_payload(
                vendor_id=vendor_id,
                booking_id=booking_id_val,
                slot_id=slot_id_val,
                user_id=user_id_val,
                username=username_val,
                game_id=game_id_val,
                game_name=game_name_val,
                date_value=date_value,
                slot_price=slot_price_val,
                start_time=start_time_val,
                end_time=end_time_val,
                console_id=console_id_val,
                status="confirmed",
                booking_status=booking_status_dim,
                squad_details=booking.squad_details or {}
            )

            # Emit after DB state is consistent; you can emit pre-commit if you prefer,
            # but post-commit avoids clients seeing uncommitted state.
            # booking service: after emit_booking_event(...) to vendor room
            try:
                socketio = current_app.extensions.get('socketio')

                # 1) Existing vendor room emit
                emit_booking_event(socketio, event="booking", data=event_payload, vendor_id=vendor_id)

                # 2) Admin tap: emit every booking event to a dedicated admin room for the dashboard bridge
                # This lets the dashboard receive ALL events upstream without pre-joining every vendor room.
                socketio.emit("booking_admin", event_payload, to="dashboard_admin")

                current_app.logger.info(
                    "confirm_booking.emit_done booking_id=%s vendor_id=%s room=%s admin_room=%s",
                    booking_id_val, vendor_id, f"vendor_{vendor_id}", "dashboard_admin"
                )
            except Exception as e:
                current_app.logger.exception(
                    "confirm_booking.emit_failed booking_id=%s vendor_id=%s error=%s",
                    booking_id_val, vendor_id, e
                )

            # Send booking confirmation email
            booking_mail(
                gamer_name      = user.name,
                gamer_phone     = user.contact_info.phone,
                gamer_email     = user.contact_info.email,
                cafe_name       = vendor.cafe_name,
                booking_date    = datetime.utcnow().strftime("%Y-%m-%d"),
                booked_for_date = str(book_date),
                booking_details = [{
                    "booking_id": booking.id,
                    "slot_time": f"{slot_obj.start_time} - {slot_obj.end_time}"
                }],
                price_paid      = amount_payable
            )

            confirmed_ids.append(booking.id)

        db.session.commit()
        return jsonify({
            'message': 'Bookings confirmed successfully',
            'confirmed_ids': confirmed_ids,
            'pass_used_id': pass_used_id,
            'pass_type': pass_type_name,
            'amount_paid': amount_payable
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error confirming booking")
        return jsonify({'error': str(e)}), 500 """

# controllers/booking_controller.py - UPDATED confirm_booking function

@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    try:
        data = request.get_json(force=True)

        booking_ids = data.get('booking_id')
        payment_id = data.get('payment_id')
        book_date_str = data.get('book_date')
        voucher_code = data.get('voucher_code')
        payment_mode = data.get('payment_mode', "payment_gateway")
        squad_payload = data.get("squad_details") or data.get("squadDetails") or None
        
        # NEW: Hour-based pass parameters
        use_hour_pass = bool(data.get('use_hour_pass', False))
        hour_pass_uid = data.get('hour_pass_uid')  # Optional: specific pass
        
        # Keep existing date-based pass logic
        use_pass = bool(data.get('use_pass', False))
        user_pass_id = data.get('user_pass_id')
        
        extra_services_list = data.get('extra_services', [])

        current_app.logger.info(f"Confirm payload: {data}")

        if not booking_ids or not book_date_str:
            return jsonify({'message': 'booking_id and book_date are required'}), 400
        
        # Validate mutual exclusivity
        if use_hour_pass and use_pass:
            return jsonify({'message': 'Cannot use both hour-based and date-based pass'}), 400
        
        if use_hour_pass and not hour_pass_uid:
            # Will auto-select best available pass
            pass

        # Parse book_date
        try:
            if 'T' in book_date_str:
                book_date = datetime.fromisoformat(book_date_str).date()
            else:
                book_date = datetime.strptime(book_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"message": "Invalid book_date format"}), 400

        if isinstance(booking_ids, int):
            booking_ids = [booking_ids]
        elif not isinstance(booking_ids, list):
            return jsonify({'message': 'booking_id must be a list or integer'}), 400
        try:
            booking_ids = [int(v) for v in booking_ids]
        except (TypeError, ValueError):
            return jsonify({'message': 'booking_id contains invalid values'}), 400
        booking_ids = list(dict.fromkeys(booking_ids))
        if len(booking_ids) > 20:
            return jsonify({'message': 'Cannot confirm more than 20 bookings per request'}), 400

        # Setup Razorpay client
        RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
        RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        razorpay_payment_verified = True

        # Verify Razorpay payment if using gateway
        if payment_mode == "payment_gateway" and not use_hour_pass:
            if not payment_id:
                return jsonify({"message": "payment_id required for payment_gateway mode"}), 400
            try:
                payment = razorpay_client.payment.fetch(payment_id)
                if payment['status'] == 'captured':
                    razorpay_payment_verified = True
                else:
                    return jsonify({"message": "Payment not successful"}), 400
            except razorpay.errors.RazorpayError as e:
                return jsonify({"message": "Payment verification failed", "error": str(e)}), 400

        # Create access code
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        confirmed_ids = []
        pass_type_name = None
        pass_used_id = None
        hour_pass_used = None
        amount_payable = 0
        total_amount_paid = 0.0
        total_hours_deducted = Decimal('0')
        mail_jobs = []
        voucher_used = False

        booking_objects = (
            Booking.query
            .options(
                joinedload(Booking.game),
                joinedload(Booking.slot),
                joinedload(Booking.squad_members),
            )
            .filter(Booking.id.in_(booking_ids))
            .all()
        )
        if not booking_objects:
            return jsonify({'message': 'No pending bookings found for confirmation'}), 404
        booking_map = {b.id: b for b in booking_objects}
        first_booking = booking_objects[0] if booking_objects else None
        first_game = first_booking.game if first_booking else None
        vendor_squad_policy = _load_squad_pricing_policy(first_game.vendor_id) if first_game else DEFAULT_SQUAD_PRICING_POLICY

        persisted_squad_details = first_booking.squad_details if first_booking and isinstance(first_booking.squad_details, dict) else {}
        if squad_payload is not None and first_game:
            try:
                persisted_squad_details = _normalize_squad_booking_payload(
                    squad_payload,
                    first_game.game_name or "",
                    vendor_policy=vendor_squad_policy,
                )
            except ValueError as squad_error:
                return jsonify({"message": str(squad_error)}), 400
            for booking in booking_objects:
                booking.squad_details = persisted_squad_details if persisted_squad_details.get("enabled") else None

        squad_enabled = bool(persisted_squad_details.get("enabled"))
        squad_console_group = str(persisted_squad_details.get("console_group") or "").strip().lower()
        squad_player_count = int(
            persisted_squad_details.get("player_count")
            or persisted_squad_details.get("playerCount")
            or 1
        )
        if squad_enabled and (use_hour_pass or use_pass):
            return jsonify({"message": "Pass-based confirmation is not supported for squad bookings."}), 400

        user_ids = {b.user_id for b in booking_objects}
        users = (
            User.query
            .options(joinedload(User.contact_info))
            .filter(User.id.in_(user_ids))
            .all()
            if user_ids else []
        )
        user_map = {u.id: u for u in users}

        vendor_ids = {b.game.vendor_id for b in booking_objects if b.game is not None}
        vendors = Vendor.query.filter(Vendor.id.in_(vendor_ids)).all() if vendor_ids else []
        vendor_map = {v.id: v for v in vendors}

        game_ids = {b.game.id for b in booking_objects if b.game is not None}
        now_ist = datetime.now(IST)
        current_date = now_ist.date()
        current_time = now_ist.time().replace(tzinfo=None)
        offers = (
            ConsolePricingOffer.query
            .filter(
                ConsolePricingOffer.is_active == True,
                ConsolePricingOffer.available_game_id.in_(game_ids),
                ConsolePricingOffer.vendor_id.in_(vendor_ids),
                ConsolePricingOffer.start_date <= current_date,
                ConsolePricingOffer.end_date >= current_date,
                or_(
                    and_(
                        ConsolePricingOffer.start_date == ConsolePricingOffer.end_date,
                        ConsolePricingOffer.start_time <= current_time,
                        ConsolePricingOffer.end_time >= current_time
                    ),
                    and_(
                        ConsolePricingOffer.start_date == current_date,
                        ConsolePricingOffer.end_date > current_date,
                        ConsolePricingOffer.start_time <= current_time
                    ),
                    and_(
                        ConsolePricingOffer.start_date < current_date,
                        ConsolePricingOffer.end_date == current_date,
                        ConsolePricingOffer.end_time >= current_time
                    ),
                    and_(
                        ConsolePricingOffer.start_date < current_date,
                        ConsolePricingOffer.end_date > current_date
                    )
                )
            )
            .all()
            if game_ids else []
        )
        effective_price_by_game = {}
        for offer in offers:
            key = offer.available_game_id
            offered = float(offer.offered_price)
            if key not in effective_price_by_game or offered < effective_price_by_game[key]:
                effective_price_by_game[key] = offered

        menu_ids = {extra.get('item_id') for extra in extra_services_list if extra.get('item_id') is not None}
        menu_rows = (
            ExtraServiceMenu.query
            .filter(ExtraServiceMenu.id.in_(menu_ids), ExtraServiceMenu.is_active == True)
            .all()
            if menu_ids else []
        )
        menu_map = {m.id: m for m in menu_rows}
        total_extras_cost = 0.0
        for extra in extra_services_list:
            menu_obj = menu_map.get(extra.get('item_id'))
            if not menu_obj:
                continue
            total_extras_cost += float(menu_obj.price or 0) * float(extra.get('quantity', 1) or 1)
        extras_total_per_booking = (total_extras_cost / len(booking_ids)) if booking_ids else 0.0

        effective_price_by_game = effective_price_by_game or {}
        base_slot_price_for_squad_by_game = {}
        squad_discount_per_slot_by_game = {}
        required_extra_controller_qty = 0
        extra_controller_fare_total = 0.0

        if squad_enabled and squad_console_group in {"ps", "xbox"}:
            required_extra_controller_qty = max(0, squad_player_count - 1)
            if required_extra_controller_qty > 0 and first_game:
                computed_controller_fare = calculate_extra_controller_fare(
                    vendor_id=first_game.vendor_id,
                    available_game_id=first_game.id,
                    quantity=required_extra_controller_qty,
                )
                if computed_controller_fare is None:
                    return jsonify({
                        "message": "Controller pricing is not configured for this console type."
                    }), 400
                extra_controller_fare_total = float(computed_controller_fare or 0.0)

        for booking in booking_objects:
            if not booking.game:
                continue
            game_effective_price = effective_price_by_game.get(
                booking.game.id,
                float(booking.game.single_slot_price or 0.0)
            )
            is_pc_squad_booking = bool(squad_enabled and squad_console_group == "pc")
            base_slot_price_for_squad_by_game[booking.game.id] = (
                game_effective_price * squad_player_count
                if is_pc_squad_booking else game_effective_price
            )
            squad_discount_per_slot_by_game[booking.game.id] = (
                (base_slot_price_for_squad_by_game[booking.game.id] * float(persisted_squad_details.get("discount_percent") or 0.0) / 100.0)
                if is_pc_squad_booking and str(persisted_squad_details.get("pricing_mode") or "") == "squad_discount"
                else 0.0
            )

        user_hash_coins = (
            UserHashCoin.query.filter(UserHashCoin.user_id.in_(user_ids)).all()
            if user_ids else []
        )
        hash_coin_map = {uhc.user_id: uhc for uhc in user_hash_coins}
        active_pass_cache = {}
        voucher_cache = {}

        for booking_id in booking_ids:
            booking = booking_map.get(booking_id)
            if not booking or booking.status == 'confirmed':
                continue

            available_game = booking.game
            slot_obj = booking.slot
            user = user_map.get(booking.user_id)
            vendor = vendor_map.get(available_game.vendor_id) if available_game else None

            if not all([available_game, vendor, slot_obj, user]):
                current_app.logger.warning(f"Booking {booking_id} missing related data")
                continue

            captain_phone = user.contact_info.phone if user and user.contact_info else ""
            if squad_enabled and not booking.squad_members:
                squad_member_bindings = _build_squad_member_bindings(
                    user,
                    user.name,
                    captain_phone,
                    persisted_squad_details,
                )
                for binding in squad_member_bindings:
                    db.session.add(
                        BookingSquadMember(
                            booking_id=int(booking.id),
                            member_user_id=binding.get("member_user_id"),
                            member_position=int(binding.get("member_position") or 0),
                            is_captain=bool(binding.get("is_captain", False)),
                            name_snapshot=str(binding.get("name_snapshot") or "")[:255],
                            phone_snapshot=str(binding.get("phone_snapshot") or "")[:50],
                        )
                    )

            # HOUR-BASED PASS LOGIC
            if use_hour_pass:
                try:
                    from services.pass_service import PassService
                    
                    # Get valid pass
                    user_hour_pass = PassService.get_valid_user_pass(
                        user_id=user.id,
                        vendor_id=vendor.id,
                        pass_uid=hour_pass_uid
                    )
                    
                    if not user_hour_pass:
                        return jsonify({'message': 'No valid hour-based pass found'}), 404
                    
                    # Calculate hours for this slot
                    hours_needed = PassService.calculate_slot_hours(
                        slot_id=slot_obj.id,
                        cafe_pass=user_hour_pass.cafe_pass
                    )
                    
                    # Check sufficient balance
                    if user_hour_pass.remaining_hours < hours_needed:
                        return jsonify({
                            'message': f'Insufficient hours. Need: {hours_needed}, Available: {user_hour_pass.remaining_hours}'
                        }), 400
                    
                    # Redeem hours
                    redemption = PassService.redeem_pass_hours(
                        user_pass_id=user_hour_pass.id,
                        vendor_id=vendor.id,
                        hours_to_deduct=hours_needed,
                        redemption_method='app_booking',
                        booking_id=booking.id,
                        session_start=slot_obj.start_time,
                        session_end=slot_obj.end_time
                    )
                    
                    hour_pass_used = user_hour_pass
                    total_hours_deducted += hours_needed
                    pass_used_id = user_hour_pass.id
                    pass_type_name = user_hour_pass.cafe_pass.name
                    
                    # Slot is free with pass
                    slot_price = effective_price_by_game.get(available_game.id, float(available_game.single_slot_price))
                    discount_amount = slot_price
                    amount_payable = 0  # Free slot
                    
                    current_app.logger.info(
                        f"Hour pass redeemed: booking_id={booking.id} hours={hours_needed} "
                        f"remaining={user_hour_pass.remaining_hours}"
                    )
                    
                except ValueError as e:
                    return jsonify({'message': str(e)}), 400
                except Exception as e:
                    current_app.logger.error(f"Hour pass redemption failed: {str(e)}")
                    return jsonify({'message': 'Pass redemption failed'}), 500

            # EXISTING DATE-BASED PASS LOGIC
            elif use_pass:
                pass_cache_key = (user.id, user_pass_id)
                if pass_cache_key not in active_pass_cache:
                    active_pass_cache[pass_cache_key] = UserPass.query.filter_by(
                        id=user_pass_id,
                        user_id=user.id,
                        is_active=True,
                        pass_mode='date_based'
                    ).first()
                active_pass = active_pass_cache[pass_cache_key]
                if not active_pass or active_pass.valid_to < book_date:
                    return jsonify({"message": "Invalid or expired date-based pass"}), 400
                pass_used_id = active_pass.id
                pass_type_name = active_pass.cafe_pass.pass_type.name if active_pass.cafe_pass.pass_type else None
                slot_price = effective_price_by_game.get(available_game.id, float(available_game.single_slot_price))
                discount_amount = slot_price
                amount_payable = 0

            # NO PASS - REGULAR PAYMENT
            else:
                slot_price = base_slot_price_for_squad_by_game.get(
                    available_game.id,
                    effective_price_by_game.get(available_game.id, float(available_game.single_slot_price or 0.0))
                )
                discount_amount = float(squad_discount_per_slot_by_game.get(available_game.id, 0.0))
                amount_payable = max(slot_price - discount_amount, 0.0)

            # Add per-slot share of extras
            amount_payable += extras_total_per_booking

            # Apply voucher discount (only on remaining amount)
            voucher = None
            if voucher_code and amount_payable > 0 and not voucher_used:
                if user.id not in voucher_cache:
                    voucher_cache[user.id] = Voucher.query.filter_by(
                        code=voucher_code,
                        user_id=user.id,
                        is_active=True
                    ).first()
                voucher = voucher_cache[user.id]
                if voucher:
                    voucher_discount = int(amount_payable * voucher.discount_percentage / 100)
                    discount_amount += voucher_discount
                    amount_payable -= voucher_discount

            # Payment processing
            if payment_mode == "wallet" and amount_payable > 0:
                BookingService.debit_wallet(user.id, booking.id, amount_payable)
                payment_mode_used = "wallet"
            elif use_hour_pass:
                payment_mode_used = "hour_pass"
            elif use_pass:
                payment_mode_used = "date_pass"
            else:
                if amount_payable == 0:
                    payment_mode_used = "free"
                elif not razorpay_payment_verified:
                    return jsonify({"message": "Payment not verified"}), 400
                else:
                    payment_mode_used = "payment_gateway"

            # Confirm booking
            booking.status = 'confirmed'
            booking.updated_at = datetime.utcnow()
            booking.access_code_id = access_code_entry.id

            # Create transaction
            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor.id,
                user_id=user.id,
                user_name=user.name,
                original_amount=slot_price + extras_total_per_booking,
                discounted_amount=discount_amount,
                amount=amount_payable,
                mode_of_payment=payment_mode_used,
                booking_date=datetime.utcnow().date(),
                booked_date=book_date,
                booking_time=datetime.utcnow().time(),
                reference_id=payment_id if payment_mode_used == "payment_gateway" else None
            )
            db.session.add(transaction)
            db.session.flush()
            total_amount_paid += float(amount_payable or 0.0)

            # Save payment mapping if gateway used
            if payment_id and payment_mode_used == "payment_gateway":
                BookingService.save_payment_transaction_mapping(booking.id, transaction.id, payment_id)

            # Save extras
            BookingExtraService.query.filter_by(booking_id=booking.id).delete()
            for extra in extra_services_list:
                menu_obj = menu_map.get(extra.get('item_id'))
                if not menu_obj:
                    continue

                quantity = extra.get('quantity', 1)
                unit_price = menu_obj.price
                total_price = unit_price * quantity

                booking_extra = BookingExtraService(
                    booking_id=booking.id,
                    menu_item_id=menu_obj.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                db.session.add(booking_extra)

            # Mark voucher as used
            if voucher:
                voucher.is_active = False
                voucher_used = True
                db.session.add(VoucherRedemptionLog(
                    user_id=user.id,
                    voucher_id=voucher.id,
                    booking_id=booking.id
                ))

            # Reward Hash Coins (skip if hour pass used to avoid double reward)
            if not use_hour_pass:
                user_hash_coin = hash_coin_map.get(user.id)
                if not user_hash_coin:
                    user_hash_coin = UserHashCoin(user_id=user.id, hash_coins=0)
                    db.session.add(user_hash_coin)
                    hash_coin_map[user.id] = user_hash_coin
                user_hash_coin.hash_coins += 1000

            # Vendor analytics (batched in same DB transaction; no per-booking commit)
            dashboard_table = f"VENDOR_{vendor.id}_DASHBOARD"
            promo_table = f"VENDOR_{vendor.id}_PROMO_DETAIL"
            book_status = "extra" if booking.status == "extra" else "upcoming"
            try:
                db.session.execute(text(f"""
                    INSERT INTO {dashboard_table}
                    (username, user_id, start_time, end_time, date, book_id, game_id, game_name, console_id, book_status)
                    VALUES (:username, :user_id, :start_time, :end_time, :date, :book_id, :game_id, :game_name, :console_id, :book_status)
                """), {
                    "username": user.name,
                    "user_id": user.id,
                    "start_time": slot_obj.start_time,
                    "end_time": slot_obj.end_time,
                    "date": book_date,
                    "book_id": booking.id,
                    "game_id": booking.game_id,
                    "game_name": available_game.game_name,
                    "console_id": -1,
                    "book_status": book_status
                })
                db.session.execute(text(f"""
                    INSERT INTO {promo_table}
                    (booking_id, transaction_id, promo_code, discount_applied, actual_price)
                    VALUES (:booking_id, :transaction_id, :promo_code, :discount_applied, :actual_price)
                """), {
                    "booking_id": booking.id,
                    "transaction_id": transaction.id,
                    "promo_code": "NOPROMO",
                    "discount_applied": "0",
                    "actual_price": amount_payable if amount_payable else 0.0
                })
            except SQLAlchemyError as analytics_exc:
                current_app.logger.warning(
                    "Non-blocking analytics insert failed for booking_id=%s: %s",
                    booking.id,
                    analytics_exc
                )

            # Emit WebSocket event
            try:
                socketio = current_app.extensions.get('socketio')
                event_payload = build_booking_event_payload(
                    vendor_id=vendor.id,
                    booking_id=booking.id,
                    slot_id=booking.slot_id,
                    user_id=user.id,
                    username=user.name,
                    game_id=booking.game_id,
                    game_name=available_game.game_name,
                    date_value=book_date,
                    slot_price=available_game.single_slot_price,
                    start_time=slot_obj.start_time,
                    end_time=slot_obj.end_time,
                    console_id=None,
                    status="confirmed",
                    booking_status="upcoming",
                    squad_details=booking.squad_details or {}
                )
                emit_booking_event(socketio, event="booking", data=event_payload, vendor_id=vendor.id)
                socketio.emit("booking_admin", event_payload, to="dashboard_admin")
            except Exception as e:
                current_app.logger.exception(f"WebSocket emit failed: {e}")

            # Send confirmation email asynchronously after commit
            if user.contact_info:
                mail_jobs.append({
                    "gamer_name": user.name,
                    "gamer_phone": user.contact_info.phone,
                    "gamer_email": user.contact_info.email,
                    "cafe_name": vendor.cafe_name,
                    "booking_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "booked_for_date": str(book_date),
                    "booking_details": [{
                        "booking_id": booking.id,
                        "slot_time": f"{slot_obj.start_time} - {slot_obj.end_time}"
                    }],
                    "price_paid": amount_payable
                })

            confirmed_ids.append(booking.id)

        if squad_enabled and squad_console_group in {"ps", "xbox"} and extra_controller_fare_total > 0 and booking_objects:
            controller_booking = booking_objects[0]
            controller_game = controller_booking.game
            controller_user = user_map.get(controller_booking.user_id)
            controller_vendor = vendor_map.get(controller_game.vendor_id) if controller_game else None
            if controller_game and controller_user and controller_vendor:
                if payment_mode == "wallet":
                    BookingService.debit_wallet(
                        controller_user.id,
                        controller_booking.id,
                        float(extra_controller_fare_total or 0.0)
                    )
                controller_payment_mode = "wallet" if payment_mode == "wallet" else "payment_gateway"
                controller_transaction = Transaction(
                    booking_id=controller_booking.id,
                    vendor_id=controller_vendor.id,
                    user_id=controller_user.id,
                    user_name=controller_user.name,
                    original_amount=extra_controller_fare_total,
                    discounted_amount=0.0,
                    amount=extra_controller_fare_total,
                    mode_of_payment=controller_payment_mode,
                    payment_use_case="app_booking",
                    booking_type="extra_controller",
                    settlement_status="paid",
                    source_channel="app",
                    base_amount=0.0,
                    meals_amount=0.0,
                    controller_amount=extra_controller_fare_total,
                    waive_off_amount=0.0,
                    booking_date=datetime.utcnow().date(),
                    booked_date=book_date,
                    booking_time=datetime.utcnow().time(),
                    reference_id=payment_id if payment_mode == "payment_gateway" else None,
                )
                db.session.add(controller_transaction)
                total_amount_paid += float(extra_controller_fare_total or 0.0)

        db.session.commit()
        _send_booking_mail_async(current_app._get_current_object(), mail_jobs)
        
        response = {
            'message': 'Bookings confirmed successfully',
            'confirmed_ids': confirmed_ids,
            'amount_paid': round(float(total_amount_paid or 0.0), 2),
            'squad_enabled': squad_enabled,
            'squad_details': persisted_squad_details if squad_enabled else {},
            'extra_controller_qty': required_extra_controller_qty,
            'extra_controller_fare': round(float(extra_controller_fare_total or 0.0), 2),
        }
        
        # Add pass info to response
        if use_hour_pass and hour_pass_used:
            response.update({
                'pass_used_type': 'hour_based',
                'pass_used_id': pass_used_id,
                'pass_uid': hour_pass_used.pass_uid,
                'pass_name': pass_type_name,
                'hours_deducted': float(total_hours_deducted),
                'remaining_hours': float(hour_pass_used.remaining_hours)
            })
        elif use_pass:
            response.update({
                'pass_used_type': 'date_based',
                'pass_used_id': pass_used_id,
                'pass_type': pass_type_name
            })
        
        return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error confirming booking")
        return jsonify({'error': str(e)}), 500


@booking_blueprint.route('/redeem-voucher', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def redeem_voucher():
    user_id = g.auth_user_id 
    data = request.json
    discount = data.get('discount_percentage')  # expected: 10, 20, 30

    if discount not in [10, 20, 30]:
        return jsonify({"message": "Invalid discount value"}), 400

    required_coins = discount * 1000  # 10% = 10k coins, 20% = 20k, etc.

    user_hash_coin = db.session.query(UserHashCoin).filter_by(user_id=user_id).first()
    if not user_hash_coin or user_hash_coin.hash_coins < required_coins:
        return jsonify({"message": "Not enough Hash Coins"}), 400

    # Deduct coins
    user_hash_coin.hash_coins -= required_coins

    # Generate unique voucher code
    import string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    voucher = Voucher(
        code=code,
        user_id=user_id,
        discount_percentage=discount,
        is_active=True
    )
    db.session.add(voucher)
    db.session.commit()

    return jsonify({
        "message": f"{discount}% voucher created successfully",
        "voucher_code": code,
        "hash_coins_remaining": user_hash_coin.hash_coins
    }), 200

@booking_blueprint.route('/users/bookings', methods=['GET'])
@auth_required_self(decrypt_user=True) 
def get_user_bookings():
    user_id = g.auth_user_id 
    bookings = BookingService.get_user_bookings(user_id)
    return jsonify([booking.to_dict() for booking in bookings])

@booking_blueprint.route('/bookings/<int:booking_id>', methods=['DELETE'])
def cancel_booking(booking_id):
    try:
        success = BookingService.cancel_booking(booking_id)
        socketio.emit('booking_updated', {'booking_id': booking_id, 'status': 'canceled'})
        return jsonify({"message": success["message"]})
    except ValueError:
        return jsonify({"message": "Booking not found"}), 404

@booking_blueprint.route('/bookings/direct', methods=['POST'])
def direct_booking():
    current_app.logger.info("Direct Booking Triggered")
    data = request.json

    user_id = data.get("user_id")
    game_id = data.get("game_id")
    booked_date = data.get("booked_date")
    selected_slots = data.get("selected_slots", [])
    console_type = data.get("console_type")
    system_number = data.get("system_number")
    payment_method = data.get("payment_method")
    payment_status = data.get("payment_status")
    total_amount = data.get("total_amount")
    additional_request = data.get("additional_request")
    user = db.session.query(User).filter(User.id == user_id).first()
    user_name = user.name

    if not user_id or not game_id or not booked_date or not selected_slots:
        return jsonify({"message": "user_id, game_id, booked_date, and selected_slots are required"}), 400

    try:
        socketio = current_app.extensions['socketio']
        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()

        if not available_game:
            return jsonify({"message": "Game not found"}), 404

        vendor_id = available_game.vendor_id

        # ✅ Fetch all required slots
        slot_entries = db.session.execute(
            text(f"""
                SELECT slot_id, available_slot, is_available
                FROM VENDOR_{vendor_id}_SLOT
                WHERE slot_id IN (SELECT id FROM slots WHERE start_time IN :selected_slots)
                AND date = :booked_date
            """),
            {"selected_slots": tuple(selected_slots), "booked_date": booked_date}
        ).fetchall()

        # ✅ Check if all slots are available
        if len(slot_entries) != len(selected_slots):
            return jsonify({"message": "One or more slots are invalid or unavailable"}), 400

        for slot in slot_entries:
            if slot[1] <= 0 or not slot[2]:
                return jsonify({"message": f"Slot {slot[0]} is fully booked"}), 400

        # ✅ Begin transaction to book all slots
        bookings = []
        for slot in slot_entries:
            slot_id = slot[0]

            booking = Booking(
                slot_id=slot_id,
                game_id=game_id,
                user_id=user_id,
                status="confirmed"
            )
            db.session.add(booking)
            bookings.append(booking)

            # ✅ Decrease `available_slot` count
            db.session.execute(
                text(f"""
                    UPDATE VENDOR_{vendor_id}_SLOT
                    SET available_slot = available_slot - 1,
                        is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                    WHERE slot_id = :slot_id
                    AND date = :booked_date;
                """),
                {"slot_id": slot_id, "booked_date": booked_date}
            )

        db.session.commit()  # ✅ Commit only after all bookings succeed
        
        _price = get_effective_price(available_game.vendor_id, available_game)
        # ✅ Store individual transaction details for each booking
        for booking in bookings:
            transaction = Transaction(
                booking_id=booking.id,  # Linking each booking
                vendor_id=vendor_id,
                user_id=user_id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_time=datetime.utcnow().time(),
                user_name=user_name,
                original_amount=_price,
                amount=_price,
                discounted_amount=0,
                mode_of_payment=payment_method,
                booking_type="direct",
                settlement_status="pending" if payment_status != "paid" else "completed"
            )
            db.session.add(transaction)

        db.session.commit()  # ✅ Commit transactions

        # ✅ Emit socket event
        for booking in bookings:
            socketio.emit('slot_booked', {
                'slot_id': booking.slot_id,
                'booking_id': booking.id,
                'status': 'booked'
            })

        return jsonify({
            "message": "Direct booking confirmed successfully",
            "bookings": [{"booking_id": b.id, "slot_id": b.slot_id} for b in bookings],
            "transaction_id": transaction.id
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to process direct booking: {str(e)}")
        return jsonify({"message": "Failed to process direct booking", "error": str(e)}), 500

@booking_blueprint.route('/bookings/reject', methods=['POST'])
def reject_booking():
    """Reject a direct booking and handle slot release & repayment."""
    try:
        data = request.json
        booking_id = data.get("booking_id")
        rejection_reason = data.get("rejection_reason", "No reason provided")
        repayment_type = data.get("repayment_type")  # refund, credit, reschedule
        user_email = data.get("user_email")

        if not booking_id or not repayment_type:
            return jsonify({"message": "booking_id and repayment_type are required"}), 400

        # Fetch booking with transaction details
        booking = db.session.query(Booking).options(joinedload(Booking.transaction)).filter_by(id=booking_id).first()

        if not booking:
            return jsonify({"message": "Booking not found"}), 404

        if not booking.transaction or booking.transaction.booking_type != "direct":
            return jsonify({"message": "Only direct bookings can be rejected"}), 400

        # Fetch slot details
        slot = db.session.query(Slot).filter_by(id=booking.slot_id).first()

        if not slot:
            return jsonify({"message": "Slot not found"}), 404

        # Release slot by updating availability
        db.session.execute(
            text(f"""
                UPDATE VENDOR_{booking.transaction.vendor_id}_SLOT
                SET available_slot = available_slot + 1, is_available = TRUE
                WHERE slot_id = :slot_id AND date = :booked_date
            """),
            {"slot_id": booking.slot_id, "booked_date": booking.transaction.booked_date}
        )

        # Update booking status
        booking.status = "rejected"

        # Create a new refund/credit/reschedule transaction
        new_transaction = Transaction(
            booking_id=booking.id,
            vendor_id=booking.transaction.vendor_id,
            user_id=booking.user_id,
            booked_date=datetime.utcnow().date(),
            booking_time=datetime.utcnow().time(),
            user_name=f"{booking.transaction.user_name} {repayment_type.upper()}-{booking.transaction.id}",
            original_amount=-booking.transaction.amount,
            discounted_amount=0,
            amount=-booking.transaction.amount,  # Negative amount for refund
            mode_of_payment=booking.transaction.mode_of_payment,
            booking_type=repayment_type,  # refund, credit, reschedule
            settlement_status="processed" if repayment_type == "refund" else "pending"
        )

        db.session.add(new_transaction)
        db.session.commit()

        BookingService.update_dashboard_booking_status(booking.transaction.id, booking.transaction.vendor_id, "rejected")

        vendor_contact = ContactInfo.query.filter_by(parent_id=booking.transaction.vendor_id, parent_type="vendor").first()
        vendor = Vendor.query.filter_by(id=booking.transaction.vendor_id).first()

        current_app.logger.info(
            f"gamer Email {user_email}; gamer name :{booking.transaction.user_name}; cafe_name: {vendor_contact.email if vendor_contact else 'N/A'} ; rejection {rejection_reason}"
        )

        # Send rejection email
        reject_booking_mail(
            gamer_name=booking.transaction.user_name,
            gamer_email=user_email,
            cafe_name=vendor.cafe_name if vendor else "N/A",
            reason=rejection_reason
        )

        return jsonify({
            "message": f"Booking {booking_id} rejected successfully",
            "status": booking.status,
            "repayment_type": repayment_type
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to reject booking", "error": str(e)}), 500

#@booking_blueprint.route('/bookings/<booking_id>', methods=['GET'])
#def get_booking_details(booking_id):
 #   try:
  #      # ✅ Fetch Booking
   #     booking = db.session.query(Booking).filter(Booking.id == booking_id).first()
   #     if not booking:
   #         return jsonify({"message": "Booking not found"}), 404
#
 #       if booking.status != "confirmed":
 #           return jsonify({"message": "Booking is not confirmed yet"}), 400
#
 #       # ✅ Fetch Slot
  #      slot = db.session.query(Slot).filter(Slot.id == booking.slot_id).first()
   #     if not slot:
    #        return jsonify({"message": "Slot not found"}), 404
#
 #       # ✅ Fetch Latest Transaction
  #      transaction = db.session.query(Transaction).filter(
   #         Transaction.booking_id == booking.id
    #    ).order_by(Transaction.id.desc()).first()

     #   if not transaction:
      #      return jsonify({"message": "Transaction not found"}), 404

        # ✅ Fetch User
       # user = db.session.query(User).filter(User.id == booking.user_id).first()
        #if not user:
         #   return jsonify({"message": "User not found"}), 404

        # ✅ Get Console ID (Fix for multiple rows issue)
        #console_entry = db.session.query(available_game_console.c.console_id).filter(
        #    available_game_console.c.available_game_id == slot.gaming_type_id
        #).first()  # Returns a tuple (console_id,)

       # console_id = console_entry[0] if console_entry else None

        # ✅ Fetch Console Details (only if console_id exists)
        #console = db.session.query(Console).filter(Console.id == console_id).first() if console_id else None

        # ✅ Fetch Contact Info (Fix incorrect filter syntax)
        #contact_info = db.session.query(ContactInfo).filter(
         #   and_(ContactInfo.parent_id == user.id, ContactInfo.parent_type == 'user')
        #).first()  # Get latest contact info if multiple exist

        # ✅ Format Response
        #booking_details = {
         #   "success": True,
          #  "booking": {
           #     "booking_id": f"BK-{booking.id}",  
            #    "date": transaction.booked_date.strftime("%Y-%m-%d"),
             #   "time_slot": {
              #      "start_time": slot.start_time.strftime("%H:%M"),
               #     "end_time": slot.end_time.strftime("%H:%M")
                #},
                #"system": console.model_number if console else "Unknown System",
              #  "game_id": booking.game_id,
               # "customer": {
                #    "name": user.name,
                 #   "email": contact_info.email if contact_info else "",
                 #   "phone": contact_info.phone if contact_info else ""
                #},
                #"amount_paid": transaction.amount
            #}
        #}

        #return jsonify(booking_details), 200

   # except Exception as e:
    #    return jsonify({"message": f"Error fetching booking details: {str(e)}"}), 500

@booking_blueprint.route('/update_booking/<int:booking_id>', methods=['PUT'])
def update_booking(booking_id):
    try:
        data = request.json  # Get JSON payload

        # ✅ Fetch existing booking
        booking = db.session.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return jsonify({"message": "Booking not found"}), 404

        available_game_id = db.session.query(AvailableGame).filter(AvailableGame.id == booking.game_id).first()
        # ✅ Fetch transactions linked to booking
        transactions = db.session.query(Transaction).filter(Transaction.booking_id == booking.id).all()

        vendor_id = available_game_id.vendor_id  # Get vendor ID from booking
        booked_date = transactions[0].booked_date  # Assuming transactions have a booked_date, use the first one

        # ✅ Fetch associated slots from `VENDOR_{vendor_id}_SLOT`
        vendor_slot_table = f'VENDOR_{vendor_id}_SLOT'
        existing_slots_query = text(f"SELECT slot_id, is_available FROM {vendor_slot_table} WHERE date = :booked_date AND vendor_id = :vendor_id")
        existing_slots = db.session.execute(existing_slots_query, {
            "booked_date": booked_date, "vendor_id": vendor_id
        }).fetchall()
        existing_slot_ids = {slot.slot_id for slot in existing_slots}


        # ✅ Fetch user details
        user = db.session.query(User).filter(User.id == booking.user_id).first()
        if not user:
            return jsonify({"message": "User not found"}), 404

        # ✅ Fetch user's contact info
        contact_info = db.session.query(ContactInfo).filter(
            and_(ContactInfo.parent_id == user.id, ContactInfo.parent_type == 'user')
        ).order_by(ContactInfo.id.desc()).first()

        # ✅ Use `no_autoflush` to prevent premature flush
        with db.session.no_autoflush:
            # ✅ Update fields if provided
            if "customer" in data:
                user.name = data["customer"].get("name", user.name)
                if contact_info:
                    contact_info.email = data["customer"].get("email", contact_info.email)
                    contact_info.phone = data["customer"].get("phone", contact_info.phone)

            # ✅ If `selected_slots` changed, update slots correctly
            if "selected_slots" in data:
                new_slots_times = set(data["selected_slots"])

                # ✅ Fetch slot IDs for new times from `VENDOR_{vendor_id}_SLOT`
                new_slot_ids = set()
                for time in new_slots_times:
                    start_time = datetime.strptime(time, "%H:%M").time()
                    end_time = (datetime.strptime(time, "%H:%M") + timedelta(minutes=30)).time()

                    slot = db.session.query(Slot).filter(Slot.gaming_type_id == available_game_id.id and Slot.start_time == start_time and Slot.end_time == end_time).first()

                    if not slot:
                        return jsonify({"message": f"Slot {time} is already booked"}), 400
                    
                    new_slot_ids.add(slot.id)

                current_app.logger.info(f"new_slot_ids {new_slot_ids}")

                if new_slot_ids != existing_slot_ids:  # Only proceed if slots are changing
                    # ✅ Step 2: Release old slots by updating availability
                    for slot_id in existing_slot_ids:
                        release_slot_query = text(f"""
                            UPDATE {vendor_slot_table} 
                            SET is_available = TRUE, available_slot = available_slot + 1
                            WHERE slot_id = :slot_id 
                            AND date = :booked_date
                            AND vendor_id = :vendor_id
                        """)
                        db.session.execute(release_slot_query, {
                            "slot_id": slot_id,
                            "booked_date": booked_date,
                            "vendor_id": vendor_id
                        })

                    # ✅ Step 3: Assign new slots by marking as unavailable
                    for slot_id in new_slot_ids:
                        assign_slot_query = text(f"""
                            UPDATE {vendor_slot_table} 
                            SET is_available = FALSE, available_slot = available_slot - 1
                            WHERE slot_id = :slot_id 
                            AND date = :booked_date
                            AND vendor_id = :vendor_id
                        """)
                        db.session.execute(assign_slot_query, {
                            "slot_id": slot_id,
                            "booked_date": booked_date,
                            "vendor_id": vendor_id
                        })

        db.session.commit()  # ✅ Commit changes in one batch

        return jsonify({"message": "Booking updated successfully"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()  # ❌ Rollback on error
        return jsonify({"message": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"message": f"Error updating booking: {str(e)}"}), 500

@booking_blueprint.route('/vendor/<int:vendor_id>/bookings', methods=['GET'])
def get_vendor_bookings(vendor_id):
    try:
        # Query bookings for the given vendor
        bookings = (db.session.query(Booking)
                    .join(Slot, Slot.id == Booking.slot_id)
                    .join(AvailableGame, AvailableGame.id == Booking.game_id)
                    .join(Console, Console.id == AvailableGame.console_id)  # assuming AvailableGame has console_id
                    .join(User, User.id == Booking.user_id)
                    .join(ContactInfo, ContactInfo.parent_id == User.id)
                    .filter(AvailableGame.vendor_id == vendor_id)
                    .all())
        
        # Prepare response data
        booking_list = []
        for booking in bookings:
            slot_time = f"{booking.slot.start_time.strftime('%H:%M')} - {booking.slot.end_time.strftime('%H:%M')}"
            system_model_number = booking.game.console.model_number if booking.game.console else None
            user_contact = booking.user.contact_info.phone if booking.user.contact_info else None
            user_email = booking.user.contact_info.email if booking.user.contact_info else None
            booking_list.append({
                "booking_id": booking.id,
                "slot_date": booking.slot.start_time.strftime('%Y-%m-%d'),
                "slot_time": slot_time,
                "system_model_number": system_model_number,
                "user_name": booking.user.name,
                "user_email": user_email,
                "user_contact": user_contact,
                "status": booking.status,
                "booking_type": "hash"  # Assuming a static value for booking type
            })
        
        # Return response as JSON
        return jsonify({"bookings": booking_list}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@booking_blueprint.route('/newBooking/vendor/<int:vendor_id>', methods=['POST'])
def new_booking(vendor_id):
    """
    Creates a new booking for the given vendor with optional extra services/meals
    Supports both regular and private booking modes via toggle
    """
    try:
        current_app.logger.info("New Booking Triggered")
        data = request.json

        console_type = data.get("consoleType")
        name = data.get("name")
        email = data.get("email")
        phone = data.get("phone")
        booked_date = data.get("bookedDate")
        slot_ids = data.get("slotId")
        payment_type = data.get("paymentType")
        console_id = data.get("consoleId")
        is_rapid_booking = data.get("isRapidBooking")
        booking_type = data.get("bookingType") or "direct"
        user_id = data.get("userId")
        waive_off_total = float(data.get("waiveOffAmount", 0.0))
        extra_controller_fare = float(data.get("extraControllerFare", 0.0))
        try:
            extra_controller_qty = int(data.get("extraControllerQty", 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"message": "extraControllerQty must be a valid integer"}), 400
        selected_meals = data.get("selectedMeals", [])
        squad_payload = data.get("squadDetails") or {}
        
        # ✅ NEW: Get booking mode from frontend
        booking_mode = data.get("bookingMode", "regular")

        # ✅ Validate booking mode
        if booking_mode not in ['regular', 'private']:
            current_app.logger.warning(f"Invalid booking_mode '{booking_mode}', defaulting to 'regular'")
            booking_mode = 'regular'

        # Normalize squad payload (frontend sends this for squad bookings).
        if not isinstance(squad_payload, dict):
            return jsonify({"message": "squadDetails must be an object"}), 400

        squad_enabled = bool(squad_payload.get("enabled", False))
        try:
            squad_player_count = int(squad_payload.get("playerCount", 1) or 1)
        except (TypeError, ValueError):
            return jsonify({"message": "squadDetails.playerCount must be a valid integer"}), 400
        try:
            suggested_extra_controller_qty = int(
                squad_payload.get("suggestedExtraControllerQty", 0) or 0
            )
        except (TypeError, ValueError):
            return jsonify({"message": "squadDetails.suggestedExtraControllerQty must be a valid integer"}), 400

        raw_members = squad_payload.get("members", [])
        if raw_members is None:
            raw_members = []
        if not isinstance(raw_members, list):
            return jsonify({"message": "squadDetails.members must be an array"}), 400

        normalized_squad_members = []
        for member in raw_members[:20]:
            if not isinstance(member, dict):
                continue
            member_name = str(member.get("name", "")).strip()
            member_phone = str(member.get("phone", "")).strip()
            if not member_name and not member_phone:
                continue
            if not member_name or not member_phone:
                return jsonify({
                    "message": "Each squad member must include both name and phone"
                }), 400
            normalized_squad_members.append({
                "name": member_name[:120],
                "phone": member_phone[:32],
            })

        normalized_squad_details = {
            "enabled": squad_enabled,
            "player_count": max(squad_player_count, 1),
            "suggested_extra_controller_qty": max(suggested_extra_controller_qty, 0),
            "members": normalized_squad_members,
        }
        if payment_type == 'Cash' and squad_enabled and not normalized_squad_details.get("batch_id"):
            normalized_squad_details["batch_id"] = str(uuid.uuid4())

        # ✅ Log received data with booking mode
        current_app.logger.info(
            f"📋 Booking Request: vendor={vendor_id}, mode={booking_mode}, "
            f"console={console_type}, slots={len(slot_ids) if slot_ids else 0}, payment={payment_type}"
        )

        # Validate required fields
        if not all([name, phone, booked_date, slot_ids, payment_type]):
            return jsonify({"message": "Missing required fields"}), 400

        # ✅ Validate console type
        if not console_type:
            return jsonify({"message": "Console type is required"}), 400

        # ✅ Get all available games for vendor
        all_games = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).all()
        
        current_app.logger.info(f"🔍 Available games for vendor {vendor_id}:")
        for game in all_games:
            current_app.logger.info(f"  Game ID {game.id}: name='{game.game_name}', price={game.single_slot_price}")

        # ✅ STRATEGY 1: Try to match by console_id if provided
        available_game = None
        
        if console_id:
            current_app.logger.info(f"🔍 Trying to find game by console_id: {console_id}")
            available_game = db.session.query(AvailableGame).filter_by(
                vendor_id=vendor_id, 
                id=console_id
            ).first()
            if available_game:
                current_app.logger.info(f"✅ Found game by ID: {available_game.game_name}")

        # ✅ STRATEGY 2: Try to match by console type using game_name
        if not available_game:
            current_app.logger.info(f"🔍 Trying to find game by console type: {console_type}")
            console_type_lower = console_type.lower()
            
            try:
                if console_type_lower == 'pc':
                    available_game = db.session.query(AvailableGame).filter(
                        AvailableGame.vendor_id == vendor_id,
                        AvailableGame.game_name.ilike('%pc%')
                    ).first()
                    
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%gaming%')
                        ).first()
                        
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%computer%')
                        ).first()
                        
                elif console_type_lower == 'ps5':
                    available_game = db.session.query(AvailableGame).filter(
                        AvailableGame.vendor_id == vendor_id,
                        AvailableGame.game_name.ilike('%ps5%')
                    ).first()
                    
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%playstation%')
                        ).first()
                        
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%sony%')
                        ).first()
                        
                elif console_type_lower == 'xbox':
                    available_game = db.session.query(AvailableGame).filter(
                        AvailableGame.vendor_id == vendor_id,
                        AvailableGame.game_name.ilike('%xbox%')
                    ).first()
                    
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%microsoft%')
                        ).first()
                        
                elif console_type_lower == 'vr':
                    available_game = db.session.query(AvailableGame).filter(
                        AvailableGame.vendor_id == vendor_id,
                        AvailableGame.game_name.ilike('%vr%')
                    ).first()
                    
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%virtual%')
                        ).first()
                        
                    if not available_game:
                        available_game = db.session.query(AvailableGame).filter(
                            AvailableGame.vendor_id == vendor_id,
                            AvailableGame.game_name.ilike('%reality%')
                        ).first()
                
                if available_game:
                    current_app.logger.info(f"✅ Found match by pattern: {available_game.game_name}")
                    
            except Exception as e:
                current_app.logger.warning(f"Error in pattern matching: {str(e)}")

        # ✅ STRATEGY 3: Fallback to first available game
        if not available_game:
            current_app.logger.warning(f"⚠️ No specific match found, using first available game for vendor {vendor_id}")
            available_game = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).first()
            if available_game:
                current_app.logger.info(f"⚠️ Using fallback game: {available_game.game_name}")

        if not available_game:
            current_app.logger.error(f"❌ No games found for vendor {vendor_id}")
            return jsonify({"message": "Game not found for this vendor"}), 404

        if extra_controller_qty < 0:
            return jsonify({"message": "extraControllerQty cannot be negative"}), 400

        if not is_controller_pricing_supported(available_game.game_name):
            # PC/VR and other unsupported console types should never carry controller surcharge.
            extra_controller_qty = 0
            extra_controller_fare = 0.0
        elif extra_controller_qty > 0:
            computed_controller_fare = calculate_extra_controller_fare(
                vendor_id=vendor_id,
                available_game_id=available_game.id,
                quantity=extra_controller_qty
            )

            if computed_controller_fare is not None:
                extra_controller_fare = computed_controller_fare
            elif extra_controller_fare <= 0:
                return jsonify({
                    "message": "Controller pricing is not configured for this console type. "
                               "Configure it in dashboard or send extraControllerFare as fallback."
                }), 400

        # ✅ LOG the final selected game with booking mode
        current_app.logger.info(
            f"🎮 FINAL SELECTED GAME: ID={available_game.id}, Name='{available_game.game_name}', "
            f"Price={available_game.single_slot_price}, Requested_Type={console_type}, Mode={booking_mode}"
        )

        vendor_squad_policy = _load_squad_pricing_policy(vendor_id)

        # Validate squad size against console policy:
        # - PC: squad discount rule-engine
        # - PS/Xbox: squad supported via controller-pricing only
        # - VR: squad not supported
        if squad_enabled:
            console_name = available_game.game_name or ""
            console_group = _resolve_console_group(console_name)
            group_rules = SQUAD_PLATFORM_RULES.get(console_group, {"enabled": False, "max_players": 1, "pricing_mode": "solo_only"})
            max_players = int(group_rules.get("max_players", 1))
            pricing_mode = str(group_rules.get("pricing_mode", "solo_only"))

            if not bool(group_rules.get("enabled")):
                return jsonify({
                    "message": f"Squad booking is not supported for {console_name}"
                }), 400
            if normalized_squad_details["player_count"] < 2:
                return jsonify({"message": "Squad booking requires at least 2 players"}), 400
            if normalized_squad_details["player_count"] > max_players:
                return jsonify({
                    "message": f"Squad player count cannot exceed {max_players} for this console type"
                }), 400

            discount_pct = _resolve_squad_discount_percent(
                console_name,
                normalized_squad_details["player_count"],
                policy=vendor_squad_policy
            )
            normalized_squad_details["console_group"] = console_group
            normalized_squad_details["max_players_for_console"] = max_players
            normalized_squad_details["pricing_mode"] = pricing_mode
            normalized_squad_details["discount_percent"] = discount_pct

            # For PS/Xbox squad sessions, pricing is controller-driven; ensure controller qty matches players.
            if pricing_mode == "controller_pricing":
                required_extra_controller_qty = max(0, int(normalized_squad_details["player_count"]) - 1)
                if required_extra_controller_qty > extra_controller_qty:
                    extra_controller_qty = required_extra_controller_qty

        # Recompute controller surcharge after squad normalization.
        if is_controller_pricing_supported(available_game.game_name) and extra_controller_qty > 0:
            computed_controller_fare = calculate_extra_controller_fare(
                vendor_id=vendor_id,
                available_game_id=available_game.id,
                quantity=extra_controller_qty
            )
            if computed_controller_fare is not None:
                extra_controller_fare = computed_controller_fare

        # Validate and calculate extra services cost
        total_meals_cost = 0
        meal_details = []
        
        if selected_meals:
            current_app.logger.info(f"Processing {len(selected_meals)} selected meals")
            
            for meal in selected_meals:
                menu_item_id = meal.get('menu_item_id')
                quantity = meal.get('quantity', 1)
                
                if not menu_item_id or quantity <= 0:
                    return jsonify({"message": "Invalid meal data provided"}), 400
                
                # Validate menu item
                menu_item = db.session.query(ExtraServiceMenu).join(
                    ExtraServiceCategory
                ).filter(
                    ExtraServiceMenu.id == menu_item_id,
                    ExtraServiceCategory.vendor_id == vendor_id,
                    ExtraServiceMenu.is_active == True,
                    ExtraServiceCategory.is_active == True
                ).first()
                
                if not menu_item:
                    return jsonify({
                        "message": f"Invalid or inactive menu item {menu_item_id} for this vendor"
                    }), 400
                
                item_total = menu_item.price * quantity
                total_meals_cost += item_total
                
                meal_details.append({
                    'menu_item': menu_item,
                    'quantity': quantity,
                    'unit_price': menu_item.price,
                    'total_price': item_total
                })
                
                current_app.logger.info(f"Added meal: {menu_item.name} x {quantity} = ₹{item_total}")

        # Find or create user
        user = (
            db.session.query(User)
            .join(ContactInfo)
            .filter(and_(User.id == user_id, ContactInfo.parent_type == 'user'))
            .first()
            if user_id
            else db.session.query(User)
            .join(ContactInfo)
            .filter(and_(ContactInfo.email == email, ContactInfo.parent_type == 'user'))
            .first()
        )

        if not user:
            user = User(
                fid=generate_fid(),
                avatar_path="Not defined",
                name=name,
                game_username=name.lower().replace(" ", "_") + str(random.randint(1000, 9999)),
                parent_type="user"

            )
            contact_info = ContactInfo(
                phone=phone,
                email=email,
                parent_id=user.id,
                parent_type="user"
            )
            user.contact_info = contact_info
            db.session.add(user)
            db.session.flush()
            current_app.logger.info(f"Created new user: {name}")

        squad_member_bindings = []
        if squad_enabled:
            squad_member_bindings.append({
                "member_user_id": int(user.id),
                "member_position": 1,
                "is_captain": True,
                "name_snapshot": str(name or "").strip()[:255] or "Captain",
                "phone_snapshot": str(phone or "").strip()[:50],
            })

            phone_binding_cache = {}
            for idx, member in enumerate(normalized_squad_members, start=2):
                member_phone = str(member.get("phone", "")).strip()[:50]
                member_name = str(member.get("name", "")).strip()[:255]
                resolved_user_id = None
                if member_phone:
                    if member_phone in phone_binding_cache:
                        resolved_user_id = phone_binding_cache[member_phone]
                    else:
                        resolved_user_id = _resolve_or_create_squad_member_user(member_name, member_phone)
                        phone_binding_cache[member_phone] = resolved_user_id

                squad_member_bindings.append({
                    "member_user_id": resolved_user_id,
                    "member_position": idx,
                    "is_captain": False,
                    "name_snapshot": member_name,
                    "phone_snapshot": member_phone,
                })
            normalized_squad_details["member_user_ids"] = [
                int(b["member_user_id"])
                for b in squad_member_bindings
                if b.get("member_user_id")
            ]

        # Get socketio instance
        socketio = current_app.extensions.get('socketio')

        # ✅ MODIFIED: Use BookingService.create_booking with booking_mode
        bookings = []
        failed_slots = []
        
        for slot_id in slot_ids:
            try:
                # ✅ Use the service method instead of direct creation
                booking = BookingService.create_booking(
                    slot_id=slot_id,
                    game_id=available_game.id,
                    user_id=user.id,
                    socketio=socketio,
                    book_date=datetime.strptime(booked_date, '%Y-%m-%d').date(),
                    is_pay_at_cafe=(payment_type == 'Cash'),
                    booking_mode=booking_mode,  # ✅ PASS BOOKING MODE HERE
                    squad_details=normalized_squad_details if squad_enabled else None,
                    slot_units=(
                        int(normalized_squad_details.get("player_count", 1))
                        if squad_enabled and str(normalized_squad_details.get("console_group", "")) == "pc"
                        else 1
                    )
                )
                
                bookings.append(booking)
                
                current_app.logger.info(
                    f"📝 CREATED BOOKING: id={booking.id}, mode={booking_mode}, "
                    f"slot_id={slot_id}, game='{available_game.game_name}', status={booking.status}"
                )
                
            except ValueError as e:
                current_app.logger.error(f"Failed to book slot {slot_id}: {str(e)}")
                failed_slots.append(slot_id)
                continue

        # Check if any bookings were created
        if not bookings:
            return jsonify({
                "success": False,
                "message": "Failed to create any bookings",
                "failed_slots": failed_slots
            }), 400

        # ✅ Since BookingService.create_booking already handles slot decrement,
        # we don't need to manually update VENDOR_X_SLOT table here

        # Add extra services to bookings
        for booking in bookings:
            for meal_detail in meal_details:
                booking_extra_service = BookingExtraService(
                    booking_id=booking.id,
                    menu_item_id=meal_detail['menu_item'].id,
                    quantity=meal_detail['quantity'],
                    unit_price=meal_detail['unit_price'],
                    total_price=meal_detail['total_price']
                )
                db.session.add(booking_extra_service)
                current_app.logger.info(f"Added extra service to booking {booking.id}: {meal_detail['menu_item'].name}")

        # Persist relational squad-member bindings per booking (captain + squad members).
        if squad_enabled and squad_member_bindings:
            for booking in bookings:
                for binding in squad_member_bindings:
                    db.session.add(
                        BookingSquadMember(
                            booking_id=int(booking.id),
                            member_user_id=binding.get("member_user_id"),
                            member_position=int(binding.get("member_position") or 0),
                            is_captain=bool(binding.get("is_captain", False)),
                            name_snapshot=str(binding.get("name_snapshot") or "")[:255],
                            phone_snapshot=str(binding.get("phone_snapshot") or "")[:50],
                        )
                    )

        # Generate access code
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        # Update bookings with access code and confirmed status
        for booking in bookings:
            booking.access_code_id = access_code_entry.id
            booking.status = "confirmed"
            booking.updated_at = datetime.utcnow()

        db.session.commit()

        # Create transaction entries
        transactions = []
        waive_off_per_slot = waive_off_total / len(bookings) if bookings else 0.0
        meals_cost_per_slot = total_meals_cost / len(bookings) if bookings and total_meals_cost > 0 else 0.0
        effective_price = get_effective_price(vendor_id, available_game)
        console_group_for_pricing = str(normalized_squad_details.get("console_group", _resolve_console_group(available_game.game_name or "")))
        is_pc_squad = bool(squad_enabled and console_group_for_pricing == "pc")
        squad_player_multiplier = int(normalized_squad_details.get("player_count", 1)) if is_pc_squad else 1
        squad_pricing_mode = str(normalized_squad_details.get("pricing_mode", _resolve_squad_pricing_mode(available_game.game_name or "")))
        squad_discount_applicable = bool(is_pc_squad and squad_pricing_mode == "squad_discount")
        squad_discount_percent = (
            _resolve_squad_discount_percent(
                available_game.game_name or "",
                int(normalized_squad_details.get("player_count", 1)),
                policy=vendor_squad_policy
            )
            if squad_discount_applicable else 0.0
        )
        base_slot_price_for_squad = effective_price * squad_player_multiplier
        squad_discount_per_slot = (base_slot_price_for_squad * squad_discount_percent / 100.0) if squad_discount_applicable else 0.0
        squad_discount_total = squad_discount_per_slot * len(bookings) if squad_discount_applicable else 0.0

        if squad_enabled:
            normalized_squad_details["discount_per_slot"] = round(squad_discount_per_slot, 2)
            normalized_squad_details["total_discount"] = round(squad_discount_total, 2)
            normalized_squad_details["slot_base_multiplier"] = int(squad_player_multiplier)
            normalized_squad_details["applied_extra_controller_qty"] = int(extra_controller_qty)
            normalized_squad_details["slot_unit_price"] = round(effective_price, 2)
            normalized_squad_details["slot_price_for_squad"] = round(base_slot_price_for_squad, 2)
            normalized_squad_details["slot_base_total_before_discount"] = round(base_slot_price_for_squad * len(bookings), 2)
            normalized_squad_details["slot_base_total_after_discount"] = round(
                max((base_slot_price_for_squad * len(bookings)) - squad_discount_total, 0.0), 2
            )

        actor = resolve_transaction_actor(request)
        payment_use_case = normalize_payment_use_case(payment_type, actor["source_channel"])
        settlement_status = resolve_settlement_status(payment_use_case)
        credit_account = None
        if payment_use_case == "monthly_credit":
            credit_account = MonthlyCreditAccount.query.filter_by(
                vendor_id=vendor_id,
                user_id=user.id,
                is_active=True
            ).first()
            if not credit_account:
                return jsonify({
                    "success": False,
                    "message": "Monthly credit account not configured for this customer."
                }), 400
            projected_credit_charge = 0.0
            for _ in bookings:
                projected_credit_charge += max(
                    ((base_slot_price_for_squad if is_pc_squad else effective_price) + meals_cost_per_slot)
                    - (waive_off_per_slot + squad_discount_per_slot),
                    0.0,
                )
            projected_credit_charge += max(float(extra_controller_fare or 0.0), 0.0)
            credit_limit_error = validate_monthly_credit_capacity(credit_account, projected_credit_charge)
            if credit_limit_error:
                return jsonify(credit_limit_error), 400

        for booking in bookings:
            if squad_enabled:
                booking.squad_details = normalized_squad_details
            base_slot_price = base_slot_price_for_squad if is_pc_squad else effective_price
            slot_meal_cost = meals_cost_per_slot
            
            original_amount = base_slot_price + slot_meal_cost
            discounted_amount = waive_off_per_slot + squad_discount_per_slot
            final_amount = max(original_amount - discounted_amount, 0.0)
            gst = calculate_gst_breakdown(vendor_id, final_amount)

            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor_id,
                user_id=user.id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                original_amount=original_amount,
                discounted_amount=discounted_amount,
                amount=final_amount,
                mode_of_payment=payment_type,
                payment_use_case=payment_use_case,
                booking_type=booking_type,
                settlement_status=settlement_status,
                source_channel=actor["source_channel"],
                initiated_by_staff_id=actor["staff_id"],
                initiated_by_staff_name=actor["staff_name"],
                initiated_by_staff_role=actor["staff_role"],
                base_amount=base_slot_price,
                meals_amount=slot_meal_cost,
                controller_amount=0.0,
                waive_off_amount=discounted_amount,
                taxable_amount=gst["taxable_amount"],
                gst_rate=gst["gst_rate"],
                cgst_amount=gst["cgst_amount"],
                sgst_amount=gst["sgst_amount"],
                igst_amount=gst["igst_amount"],
                total_with_tax=gst["total_with_tax"]
            )
            db.session.add(transaction)
            db.session.flush()
            transactions.append(transaction)

            if credit_account and final_amount > 0:
                due_date = compute_credit_due_date(
                    datetime.strptime(booked_date, "%Y-%m-%d").date(),
                    credit_account.billing_cycle_day
                )
                db.session.add(
                    MonthlyCreditLedger(
                        account_id=credit_account.id,
                        transaction_id=transaction.id,
                        entry_type="charge",
                        amount=final_amount,
                        description=f"Booking charge #{booking.id}",
                        booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                        due_date=due_date,
                        source_channel=actor["source_channel"],
                        staff_id=actor["staff_id"],
                        staff_name=actor["staff_name"],
                    )
                )
                credit_account.outstanding_amount = float(credit_account.outstanding_amount or 0) + final_amount

        # Handle extra controller fare
        if extra_controller_fare > 0:
            gst = calculate_gst_breakdown(vendor_id, extra_controller_fare)
            controller_transaction = Transaction(
                booking_id=bookings[0].id,
                vendor_id=vendor_id,
                user_id=user.id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                original_amount=extra_controller_fare,
                discounted_amount=0,
                amount=extra_controller_fare,
                mode_of_payment=payment_type,
                payment_use_case=payment_use_case,
                booking_type="extra_controller",
                settlement_status=settlement_status,
                source_channel=actor["source_channel"],
                initiated_by_staff_id=actor["staff_id"],
                initiated_by_staff_name=actor["staff_name"],
                initiated_by_staff_role=actor["staff_role"],
                base_amount=0.0,
                meals_amount=0.0,
                controller_amount=extra_controller_fare,
                waive_off_amount=0.0,
                taxable_amount=gst["taxable_amount"],
                gst_rate=gst["gst_rate"],
                cgst_amount=gst["cgst_amount"],
                sgst_amount=gst["sgst_amount"],
                igst_amount=gst["igst_amount"],
                total_with_tax=gst["total_with_tax"]
            )
            db.session.add(controller_transaction)
            db.session.flush()
            transactions.append(controller_transaction)

            if credit_account:
                due_date = compute_credit_due_date(
                    datetime.strptime(booked_date, "%Y-%m-%d").date(),
                    credit_account.billing_cycle_day
                )
                db.session.add(
                    MonthlyCreditLedger(
                        account_id=credit_account.id,
                        transaction_id=controller_transaction.id,
                        entry_type="charge",
                        amount=extra_controller_fare,
                        description=f"Extra controller charge #{bookings[0].id}",
                        booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                        due_date=due_date,
                        source_channel=actor["source_channel"],
                        staff_id=actor["staff_id"],
                        staff_name=actor["staff_name"],
                    )
                )
                credit_account.outstanding_amount = float(credit_account.outstanding_amount or 0) + extra_controller_fare

        # Resolve runtime lifecycle and console assignment.
        # If slot is live in IST, assign console now and start as current.
        booked_for_date_obj = datetime.strptime(booked_date, "%Y-%m-%d").date()
        slot_map = {
            int(s.id): s
            for s in Slot.query.filter(Slot.id.in_([b.slot_id for b in bookings])).all()
        }
        booking_runtime = {}
        for booking in bookings:
            slot_obj = slot_map.get(int(booking.slot_id))
            runtime_status = "upcoming"
            runtime_console_id = int(console_id) if console_id is not None else -1

            if slot_obj and _is_slot_live_now_ist(booked_for_date_obj, slot_obj.start_time, slot_obj.end_time):
                console_group = str(normalized_squad_details.get("console_group", "")).lower()
                is_pc_squad = bool(squad_enabled and console_group == "pc")
                required_console_count = (
                    int(normalized_squad_details.get("player_count", 1))
                    if is_pc_squad
                    else 1
                )
                required_console_count = max(required_console_count, 1)

                reserved_console_ids = []
                if is_rapid_booking and console_id is not None:
                    reserved_specific = _reserve_specific_console(
                        vendor_id=vendor_id,
                        game_id=available_game.id,
                        console_id=int(console_id),
                    )
                    if reserved_specific is not None:
                        reserved_console_ids.append(int(reserved_specific))

                remaining_needed = required_console_count - len(reserved_console_ids)
                if remaining_needed > 0:
                    reserved_console_ids.extend(
                        _reserve_multiple_consoles(
                            vendor_id=vendor_id,
                            game_id=available_game.id,
                            quantity=remaining_needed,
                        )
                    )

                if len(reserved_console_ids) >= required_console_count:
                    reserved_console_ids = reserved_console_ids[:required_console_count]
                    runtime_status = "current"
                    runtime_console_id = int(reserved_console_ids[0])
                    booking.status = "checked_in"
                    if squad_enabled and isinstance(booking.squad_details, dict):
                        updated_squad = dict(booking.squad_details)
                        updated_squad["assigned_console_ids"] = [int(cid) for cid in reserved_console_ids]
                        console_rows = (
                            Console.query
                            .filter(Console.id.in_([int(cid) for cid in reserved_console_ids]))
                            .all()
                        )
                        label_by_console = {
                            int(c.id): str(c.model_number or f"Console {c.id}")
                            for c in console_rows
                        }
                        updated_squad["assigned_console_labels"] = {
                            str(cid): label_by_console.get(int(cid), f"Console {cid}")
                            for cid in reserved_console_ids
                        }

                        if is_pc_squad:
                            squad_members = (
                                BookingSquadMember.query
                                .filter(BookingSquadMember.booking_id == int(booking.id))
                                .order_by(BookingSquadMember.member_position.asc())
                                .all()
                            )
                            member_console_map = []
                            for idx, member in enumerate(squad_members):
                                if idx >= len(reserved_console_ids):
                                    break
                                mapped_console_id = int(reserved_console_ids[idx])
                                member_console_map.append({
                                    "member_position": int(member.member_position or idx + 1),
                                    "member_user_id": int(member.member_user_id) if member.member_user_id else None,
                                    "member_name": str(member.name_snapshot or f"Player {idx + 1}"),
                                    "console_id": mapped_console_id,
                                    "console_label": label_by_console.get(mapped_console_id, f"Console {mapped_console_id}"),
                                })
                            if member_console_map:
                                updated_squad["member_console_map"] = member_console_map

                        booking.squad_details = updated_squad
                else:
                    if reserved_console_ids:
                        _release_reserved_consoles(vendor_id=vendor_id, console_ids=reserved_console_ids)
                    current_app.logger.warning(
                        "Insufficient consoles for live booking_id=%s vendor_id=%s game_id=%s required=%s reserved=%s",
                        booking.id, vendor_id, available_game.id, required_console_count, len(reserved_console_ids)
                    )

            booking_runtime[int(booking.id)] = {
                "dashboard_status": runtime_status,
                "console_id": runtime_console_id,
            }

        db.session.commit()

        # Dashboard and promo table entries
        for trans in transactions:
            meta = booking_runtime.get(int(trans.booking_id))
            if meta:
                console_id_val = int(meta["console_id"])
                dashboard_status = str(meta["dashboard_status"])
            else:
                console_id_val = int(console_id) if console_id is not None else -1
                dashboard_status = "upcoming"
            BookingService.insert_into_vendor_dashboard_table(trans.id, console_id_val, dashboard_status)
            BookingService.insert_into_vendor_promo_table(trans.id, console_id_val)

        # Prepare booking details for email
        booking_details = []
        for booking in bookings:
            slot_obj = db.session.query(Slot).filter_by(id=booking.slot_id).first()
            slot_time = f"{str(slot_obj.start_time)} - {str(slot_obj.end_time)}" if slot_obj else "N/A"
            booking_details.append({
                "booking_id": booking.id,
                "slot_time": slot_time
            })

        # Calculate total amount paid
        total_base_cost = base_slot_price_for_squad * len(bookings) if squad_enabled else effective_price * len(bookings)
        total_paid = max(
            total_base_cost + total_meals_cost + extra_controller_fare - waive_off_total - squad_discount_total,
            0.0
        )

        # Send booking confirmation email
        cafe_name = db.session.query(Vendor).filter_by(id=vendor_id).first().cafe_name
        
        email_meal_details = []
        if meal_details:
            for detail in meal_details:
                email_meal_details.append({
                    "name": detail['menu_item'].name,
                    "quantity": detail['quantity'],
                    "unit_price": detail['unit_price'],
                    "total_price": detail['total_price']
                })

        booking_mail(
            gamer_name=name,
            gamer_phone=phone,
            gamer_email=email,
            cafe_name=cafe_name,
            booking_date=datetime.utcnow().strftime("%Y-%m-%d"),
            booked_for_date=booked_date,
            booking_details=booking_details,
            price_paid=total_paid,
            extra_meals=email_meal_details,
            extra_controller_fare=extra_controller_fare,
            waive_off_amount=waive_off_total
        )

        # ✅ ENHANCED SUCCESS LOG with booking mode
        current_app.logger.info(
            f"✅ BOOKING SUCCESS: mode={booking_mode}, console_type={console_type}, "
            f"game_id={available_game.id}, game_name='{available_game.game_name}', "
            f"bookings_created={len(bookings)}, failed_slots={len(failed_slots)}, total_cost=₹{total_paid}"
        )

        # ✅ Build response with booking mode
        response = {
            "success": True,
            "message": f"{'Private' if booking_mode == 'private' else 'Regular'} booking confirmed successfully",
            "booking_ids": [b.id for b in bookings],
            "transaction_ids": [t.id for t in transactions],
            "access_code": code,
            "booking_mode": booking_mode,  # ✅ Return booking mode
            "squad_details": normalized_squad_details if squad_enabled else {
                "enabled": False,
                "player_count": 1,
                "suggested_extra_controller_qty": 0,
                "members": []
            },
            "squad_member_bindings": squad_member_bindings if squad_enabled else [],
            "requested_console_type": console_type,
            "matched_game_id": available_game.id,
            "matched_game_name": available_game.game_name,
            "total_base_cost": total_base_cost,
            "total_meals_cost": total_meals_cost,
            "squad_discount_percent": squad_discount_percent,
            "squad_discount_amount": squad_discount_total,
            "extra_controller_fare": extra_controller_fare,
            "extra_controller_qty": extra_controller_qty,
            "waive_off_amount": waive_off_total,
            "final_amount": total_paid,
            "pricing_engine": {
                "slot_base_total": round(total_base_cost, 2),
                "squad_discount_amount": round(squad_discount_total, 2),
                "manual_waive_off_amount": round(waive_off_total, 2),
                "meals_total": round(total_meals_cost, 2),
                "extra_controller_total": round(extra_controller_fare, 2),
                "final_amount": round(total_paid, 2),
            },
            "source_channel": actor["source_channel"],
            "staff": {
                "id": actor["staff_id"],
                "name": actor["staff_name"],
                "role": actor["staff_role"]
            },
            "payment_use_case": payment_use_case,
            "selected_meals": [
                {
                    "name": detail['menu_item'].name,
                    "category": detail['menu_item'].category.name,
                    "quantity": detail['quantity'],
                    "unit_price": detail['unit_price'],
                    "total_price": detail['total_price']
                }
                for detail in meal_details
            ]
        }

        # ✅ Add failed slots info if any
        if failed_slots:
            response['partial_success'] = True
            response['failed_slots'] = failed_slots
            response['message'] = f"Created {len(bookings)} bookings ({booking_mode} mode), {len(failed_slots)} slots failed"

        return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"❌ Failed to process booking: {str(e)}")
        current_app.logger.error(f"❌ Exception details: {e.__class__.__name__}: {str(e)}")
        import traceback
        current_app.logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return jsonify({
            "success": False,
            "message": "Failed to process booking", 
            "error": str(e)
        }), 500




        
        # Add this route to get complete booking details including extra services

@booking_blueprint.route('/booking/<int:booking_id>/details', methods=['GET', 'OPTIONS'])
def get_booking_details(booking_id):
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        return response
        
    try:
        current_app.logger.info(f"Fetching details for booking {booking_id}")
        
        # ✅ FIX: Updated eager loading with correct relationship names
        booking = (
            Booking.query
            .options(
                # Fixed: Use 'extra_service_menu' instead of 'menu_item'
                joinedload(Booking.booking_extra_services).joinedload(BookingExtraService.extra_service_menu).joinedload('category'),
                joinedload(Booking.game),
                joinedload(Booking.slot),
                joinedload(Booking.user).joinedload('contact_info'),
                joinedload(Booking.game).joinedload('console')
            )
            .filter(Booking.id == booking_id)
            .first()
        )
        
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404
        
        # ✅ REMOVED: Status check so modal can show existing meals even for non-confirmed bookings
        # if booking.status != "confirmed":
        #     return jsonify({"message": "Booking is not confirmed yet"}), 400
        
        user = booking.user
        contact_info = user.contact_info if user else None
        slot = booking.slot
        game = booking.game
        console = getattr(game, 'console', None)
        
        transactions = (
            Transaction.query.filter(Transaction.booking_id == booking.id).all()
        )
        squad_members = (
            BookingSquadMember.query
            .filter(BookingSquadMember.booking_id == booking.id)
            .order_by(BookingSquadMember.member_position.asc())
            .all()
        )
        
        base_price = sum(t.amount for t in transactions if t.booking_type == 'direct')
        extra_services_price = 0
        extra_services_list = []
        
        # ✅ FIX: Use correct relationship name 'extra_service_menu'
        for bes in booking.booking_extra_services:
            item = bes.extra_service_menu  # Changed from bes.menu_item to bes.extra_service_menu
            category = getattr(item, 'category', None)
            extra_services_list.append({
                "id": bes.id,
                "menu_item_id": bes.menu_item_id,
                "menu_item_name": item.name if item else "Unknown",
                "category_name": category.name if category else "Unknown",
                "quantity": bes.quantity,
                "unit_price": float(bes.unit_price),
                "total_price": float(bes.total_price)
            })
            extra_services_price += bes.total_price
        
        # ✅ ENHANCED: Include additional meals transactions
        extra_controller_price = sum(t.amount for t in transactions if t.booking_type == 'extra_controller')
        additional_meals_price = sum(t.amount for t in transactions if t.booking_type == 'additional_meals')
        total_amount = base_price + extra_services_price + extra_controller_price + additional_meals_price
        
        # Format slot times nicely
        def format_time(t):
            if t:
                return t.strftime('%I:%M %p')
            return 'N/A'
        
        response = {
            "booking_id": booking.id,
            "status": booking.status,
            "squad_details": booking.squad_details or {},
            "squad_members": [member.to_dict() for member in squad_members],
            "user": {
                "id": user.id if user else None,
                "name": user.name if user else "Unknown",
                "email": contact_info.email if contact_info else None,
                "phone": contact_info.phone if contact_info else None
            },
            "game": {
                "id": game.id if game else None,
                "name": game.game_name if game else "Unknown",
                "vendor_id": game.vendor_id if game else None
            },
            "console": {
                "id": console.id if console else None,
                "model_number": console.model_number if console else "Unknown"
            },
            "slot": {
                "id": slot.id if slot else None,
                "start_time": format_time(getattr(slot, 'start_time', None)),
                "end_time": format_time(getattr(slot, 'end_time', None))
            },
            "pricing": {
                "base_price": float(base_price),
                "extra_services_price": float(extra_services_price),
                "extra_controller_price": float(extra_controller_price),
                "additional_meals_price": float(additional_meals_price),  # ✅ NEW: Added this
                "total_amount": float(total_amount)
            },
            "extra_services": extra_services_list,
            "transactions": [
                {
                    "id": t.id,
                    "original_amount": float(t.original_amount),
                    "discounted_amount": float(t.discounted_amount),
                    "final_amount": float(t.amount),
                    "mode_of_payment": t.mode_of_payment,
                    "booking_type": t.booking_type,
                    "settlement_status": t.settlement_status
                } for t in transactions
            ]
        }
        
        current_app.logger.info(f"✅ Successfully retrieved booking details for {booking_id} with {len(extra_services_list)} extra services")
        return jsonify({"success": True, "booking": response}), 200

    except Exception as ex:
        current_app.logger.error(f"❌ Error fetching booking details {booking_id}: {ex}")
        import traceback
        current_app.logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(ex)}), 500

        # Quick validation route for menu items

@booking_blueprint.route('/vendor/<int:vendor_id>/validate-meals', methods=['POST'])
def validate_selected_meals(vendor_id):
    """Validate selected meals and return pricing info"""
    try:
        data = request.json
        selected_meals = data.get('selectedMeals', [])
        
        if not selected_meals:
            return jsonify({
                'success': True,
                'total_cost': 0,
                'validated_meals': []
            }), 200

        validated_meals = []
        total_cost = 0

        for meal in selected_meals:
            menu_item_id = meal.get('menu_item_id')
            quantity = meal.get('quantity', 1)

            menu_item = db.session.query(ExtraServiceMenu).join(
                ExtraServiceCategory
            ).filter(
                ExtraServiceMenu.id == menu_item_id,
                ExtraServiceCategory.vendor_id == vendor_id,
                ExtraServiceMenu.is_active == True,
                ExtraServiceCategory.is_active == True
            ).first()

            if not menu_item:
                return jsonify({
                    'success': False,
                    'error': f'Menu item {menu_item_id} not found or inactive'
                }), 400

            item_total = menu_item.price * quantity
            total_cost += item_total

            validated_meals.append({
                'menu_item_id': menu_item.id,
                'name': menu_item.name,
                'category': menu_item.category.name,
                'unit_price': float(menu_item.price),
                'quantity': quantity,
                'total_price': float(item_total)
            })

        return jsonify({
            'success': True,
            'total_cost': float(total_cost),
            'validated_meals': validated_meals
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Get vendor's booking statistics including meals
@booking_blueprint.route('/vendor/<int:vendor_id>/booking-stats', methods=['GET'])
def get_vendor_booking_stats(vendor_id):
    """Get booking statistics including extra services revenue"""
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import func, and_

        # Date range (last 30 days)
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)

        # Get booking statistics
        booking_stats = db.session.query(
            func.count(Booking.id).label('total_bookings'),
            func.count(func.distinct(Booking.user_id)).label('unique_customers')
        ).join(AvailableGame).filter(
            AvailableGame.vendor_id == vendor_id,
            Booking.status == 'confirmed'
        ).first()

        # Get extra services statistics
        extra_services_stats = db.session.query(
            func.count(BookingExtraService.id).label('total_extra_services'),
            func.sum(BookingExtraService.total_price).label('total_extra_revenue'),
            func.count(func.distinct(BookingExtraService.menu_item_id)).label('unique_items_ordered')
        ).join(Booking).join(AvailableGame).filter(
            AvailableGame.vendor_id == vendor_id,
            Booking.status == 'confirmed'
        ).first()

        # Most popular menu items
        popular_items = db.session.query(
            ExtraServiceMenu.name,
            ExtraServiceCategory.name.label('category_name'),
            func.sum(BookingExtraService.quantity).label('total_quantity'),
            func.sum(BookingExtraService.total_price).label('total_revenue')
        ).join(BookingExtraService).join(Booking).join(AvailableGame).join(
            ExtraServiceCategory, ExtraServiceMenu.category_id == ExtraServiceCategory.id
        ).filter(
            AvailableGame.vendor_id == vendor_id,
            Booking.status == 'confirmed'
        ).group_by(
            ExtraServiceMenu.id, ExtraServiceMenu.name, ExtraServiceCategory.name
        ).order_by(func.sum(BookingExtraService.quantity).desc()).limit(5).all()

        return jsonify({
            'success': True,
            'stats': {
                'bookings': {
                    'total_bookings': booking_stats.total_bookings or 0,
                    'unique_customers': booking_stats.unique_customers or 0
                },
                'extra_services': {
                    'total_orders': extra_services_stats.total_extra_services or 0,
                    'total_revenue': float(extra_services_stats.total_extra_revenue or 0),
                    'unique_items_ordered': extra_services_stats.unique_items_ordered or 0
                },
                'popular_items': [
                    {
                        'name': item.name,
                        'category': item.category_name,
                        'total_quantity': item.total_quantity,
                        'total_revenue': float(item.total_revenue)
                    }
                    for item in popular_items
                ]
            }
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@booking_blueprint.route('/extraBooking', methods=['POST'])
def extra_booking():
    """
    Records extra booking (time extended) played by the user in a gaming cafe, with waive-off functionality.
    """
    try:
        data = request.get_json(silent=True) or {}

        required_fields = ["consoleNumber", "consoleType", "date", "slotId", "userId", "username", "amount", "gameId", "modeOfPayment", "vendorId"]
        if not all(data.get(field) is not None for field in required_fields):
            return jsonify({"message": "Missing required fields"}), 400

        console_number = data["consoleNumber"]
        console_type = data["consoleType"]
        booked_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        slot_id = int(data["slotId"])
        user_id = int(data["userId"])
        username = data["username"]
        amount = float(data["amount"])
        game_id = int(data["gameId"])
        mode_of_payment = str(data["modeOfPayment"]).strip().lower()
        vendor_id = int(data["vendorId"])
        waive_off_amount = float(data.get("waiveOffAmount", 0.0))
        reference_id = data.get("reference_id")

        actor = resolve_transaction_actor(request)
        payment_use_case = normalize_payment_use_case(mode_of_payment, actor["source_channel"])
        settlement_status = resolve_settlement_status(payment_use_case)
        credit_account = None
        if payment_use_case == "monthly_credit":
            credit_account = MonthlyCreditAccount.query.filter_by(
                vendor_id=vendor_id,
                user_id=user_id,
                is_active=True
            ).first()
            if not credit_account:
                return jsonify({
                    "success": False,
                    "message": "Monthly credit account not configured for this customer."
                }), 400

        user = db.session.query(User).filter_by(id=user_id).first()
        slot = db.session.query(Slot).filter_by(id=slot_id).first()
        if not user or not slot:
            return jsonify({"message": "User or slot not found"}), 404

        # Attach extra charge to current booking when possible for transparent settlement.
        primary_booking = (
            Booking.query
            .filter_by(slot_id=slot_id, game_id=game_id, user_id=user_id)
            .filter(Booking.status.in_(["confirmed", "checked_in", "completed", "extra", "pending_verified", "pending_acceptance"]))
            .order_by(Booking.id.desc())
            .first()
        )
        if not primary_booking:
            primary_booking = Booking(slot_id=slot_id, game_id=game_id, user_id=user_id, status="extra")
            db.session.add(primary_booking)
            db.session.flush()

        squad_details = primary_booking.squad_details if isinstance(primary_booking.squad_details, dict) else {}
        squad_console_group = str(squad_details.get("console_group") or "").strip().lower()
        squad_player_count = int(squad_details.get("player_count") or squad_details.get("playerCount") or 1)
        is_pc_squad = bool(
            squad_console_group == "pc"
            and squad_player_count > 1
            and (squad_details.get("enabled") is True or squad_player_count > 1)
        )
        effective_multiplier = max(squad_player_count, 1) if is_pc_squad else 1

        # Frontend sends overtime amount at per-player rate.
        # For PC squad, apply to full squad so billing remains transparent and complete.
        original_amount = amount * effective_multiplier
        discounted_amount = waive_off_amount
        final_amount = max(original_amount - discounted_amount, 0.0)
        if credit_account:
            credit_limit_error = validate_monthly_credit_capacity(credit_account, final_amount)
            if credit_limit_error:
                return jsonify(credit_limit_error), 400
        gst = calculate_gst_breakdown(vendor_id, final_amount)

        transaction = Transaction(
            booking_id=primary_booking.id,
            vendor_id=vendor_id,
            user_id=user_id,
            booked_date=booked_date,
            booking_date=datetime.utcnow().date(),
            booking_time=datetime.utcnow().time(),
            user_name=username,
            original_amount=original_amount,
            discounted_amount=discounted_amount,
            amount=final_amount,
            mode_of_payment=mode_of_payment,
            payment_use_case=payment_use_case,
            booking_type="extra",
            settlement_status=settlement_status,
            source_channel=actor["source_channel"],
            initiated_by_staff_id=actor["staff_id"],
            initiated_by_staff_name=actor["staff_name"],
            initiated_by_staff_role=actor["staff_role"],
            base_amount=final_amount,
            meals_amount=0.0,
            controller_amount=0.0,
            waive_off_amount=discounted_amount,
            taxable_amount=gst["taxable_amount"],
            gst_rate=gst["gst_rate"],
            cgst_amount=gst["cgst_amount"],
            sgst_amount=gst["sgst_amount"],
            igst_amount=gst["igst_amount"],
            total_with_tax=gst["total_with_tax"],
            reference_id=reference_id,
        )
        db.session.add(transaction)

        if is_pc_squad:
            updated_squad = dict(squad_details)
            ledger = updated_squad.get("extra_session_ledger")
            if not isinstance(ledger, list):
                ledger = []
            ledger.append({
                "recorded_at": datetime.utcnow().isoformat(),
                "slot_id": int(slot_id),
                "console_group": "pc",
                "player_count": int(effective_multiplier),
                "per_player_amount": round(float(amount), 2),
                "original_amount": round(float(original_amount), 2),
                "waive_off_amount": round(float(discounted_amount), 2),
                "final_amount": round(float(final_amount), 2),
                "transaction_id_preview": None,
                "recorded_by": actor["source_channel"],
            })
            updated_squad["extra_session_ledger"] = ledger
            updated_squad["last_extra_charge_amount"] = round(float(final_amount), 2)
            updated_squad["last_extra_charge_multiplier"] = int(effective_multiplier)
            primary_booking.squad_details = updated_squad

        db.session.commit()

        if is_pc_squad and isinstance(primary_booking.squad_details, dict):
            # Backfill transaction id after commit for traceability.
            updated_squad = dict(primary_booking.squad_details)
            ledger = updated_squad.get("extra_session_ledger")
            if isinstance(ledger, list) and ledger:
                ledger[-1]["transaction_id_preview"] = int(transaction.id)
                updated_squad["extra_session_ledger"] = ledger
                primary_booking.squad_details = updated_squad
                db.session.commit()

        BookingService.insert_into_vendor_dashboard_table(transaction.id, console_number)
        BookingService.insert_into_vendor_promo_table(transaction.id, console_number)

        gamer_email = user.contact_info.email if user and user.contact_info else "no-reply@example.com"

        if not slot or not slot.start_time or not slot.end_time:
            slot_time_str = "N/A"
        else:
            slot_time_str = f"{slot.start_time.strftime('%-I:%M %p')} to {slot.end_time.strftime('%-I:%M %p')}"

        # Send the extra booking email
        extra_booking_time_mail(
            username=username,
            user_email=gamer_email,
            booked_date=booked_date.strftime("%Y-%m-%d"),
            slot_time=slot_time_str,
            console_type=console_type,
            console_number=console_number,
            amount=final_amount,  # Use final_amount after waive-off
            mode_of_payment=mode_of_payment
        )

        summary = compute_booking_financial_summary(primary_booking.id)

        return jsonify({
            "message": "Extra booking recorded successfully",
            "booking_id": primary_booking.id,
            "transaction_id": transaction.id,
            "payment_status": {
                "label": "Extra Payment Required" if summary["amount_due"] > 0 else "Settled",
                "amount_paid": summary["amount_paid"],
                "amount_due": summary["amount_due"],
                "total_charged": summary["total_charged"],
            },
            "session_notice": f"The session for {username} on {console_type} #{console_number} has exceeded the allotted time.",
            "financial_summary": summary,
            "squad_charge": {
                "is_pc_squad": is_pc_squad,
                "player_count": int(effective_multiplier),
                "per_player_amount": round(float(amount), 2),
                "charged_original_amount": round(float(original_amount), 2),
                "charged_final_amount": round(float(final_amount), 2),
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error recording extra booking: {str(e)}")
        return jsonify({"message": "Failed to record extra booking", "error": str(e)}), 500

@booking_blueprint.route('/getAllBooking/vendor/<int:vendor_id>/<string:date>/', methods=['GET'])
def get_all_booking(vendor_id, date):
    """
    Retrieves all booking details for a given vendor from the given date onwards.
    """
    try:
        current_app.logger.info("Fetching all bookings for vendor_id=%s from date=%s onwards", vendor_id, date)

        # Convert date format (YYYYMMDD → YYYY-MM-DD)
        formatted_date = datetime.strptime(date, "%Y%m%d").date()

        # Query to fetch booking details for given vendor from the date onwards
        results = db.session.query(
            Booking.id.label("bookingId"),
            Transaction.booked_date.label("bookingDate"),
            Transaction.booking_time.label("bookingTime"),
            User.name.label("userName"),
            AvailableGame.game_name.label("consoleType"),
            AvailableGame.id.label("consoleTypeId"),
            Transaction.booked_date.label("bookedDate"),
            Slot.start_time.label("startTime"),
            Slot.end_time.label("endTime"),
            Booking.status.label("status"),
            Transaction.booking_type.label("type"),
            Transaction.user_id.label("userId"),
            Transaction.booked_date.label("bookedDate")
        ).join(Transaction, Booking.id == Transaction.booking_id) \
         .join(User, Booking.user_id == User.id) \
         .join(AvailableGame, Booking.game_id == AvailableGame.id) \
         .join(Slot, Booking.slot_id == Slot.id) \
         .filter(Transaction.vendor_id == vendor_id, Transaction.booked_date >= formatted_date) \
         .distinct(Booking.id) \
         .order_by(Booking.id, Transaction.booking_time.desc()) \
         .all()

        # Convert results into a structured list
        bookings = [{
            "bookingId": row.bookingId,
            "bookingDate": row.bookingDate.strftime("%Y-%m-%d"),
            "bookingTime": row.bookingTime.strftime("%H:%M:%S"),
            "userName": row.userName,
            "consoleType": row.consoleType,
            "consoleTypeId": row.consoleTypeId,
            "bookedDate": row.bookedDate.strftime("%Y-%m-%d"),
            "startTime": row.startTime.strftime("%H:%M:%S"),
            "endTime": row.endTime.strftime("%H:%M:%S"),
            "status": row.status,
            "type": row.type,
            "userId":row.userId,
            "bookedDate":row.bookedDate
        } for row in results]

        return jsonify(bookings), 200

    except Exception as e:
        current_app.logger.error(f"Failed to fetch bookings: {str(e)}")
        return jsonify({"message": "Failed to fetch bookings", "error": str(e)}), 500

@booking_blueprint.route('/vendor/<string:vendor_id>/users', methods=['GET', 'POST'])
def get_user_details(vendor_id):
    try:
        if request.method == 'POST':
            body = request.get_json(silent=True) or {}

            name = str(body.get("name") or "").strip()
            phone = str(body.get("phone") or "").strip()
            email = str(body.get("email") or "").strip().lower()
            whatsapp = str(body.get("whatsapp_number") or "").strip()
            address = str(body.get("address") or "").strip()

            if not name:
                return jsonify({"success": False, "message": "name is required"}), 400
            if not phone and not email:
                return jsonify({"success": False, "message": "phone or email is required"}), 400

            # Deduplicate by phone/email before creating a new user.
            existing_contact = None
            if phone:
                existing_contact = ContactInfo.query.filter_by(parent_type="user", phone=phone).first()
            if not existing_contact and email:
                existing_contact = ContactInfo.query.filter_by(parent_type="user", email=email).first()

            if existing_contact:
                existing_user = User.query.filter_by(id=existing_contact.parent_id).first()
                if existing_user:
                    return jsonify({
                        "success": True,
                        "created": False,
                        "user": {
                            "id": existing_user.id,
                            "name": existing_user.name,
                            "email": existing_contact.email,
                            "phone": existing_contact.phone,
                        }
                    }), 200

            slug = "".join(ch for ch in name.lower() if ch.isalnum() or ch == " ").strip().replace(" ", "_")
            if not slug:
                slug = "gamer"
            game_username = f"{slug}{random.randint(1000, 9999)}"
            while User.query.filter_by(game_username=game_username).first():
                game_username = f"{slug}{random.randint(1000, 9999)}"

            if not email:
                safe_phone = "".join(ch for ch in phone if ch.isdigit())[-10:] or str(random.randint(1000000000, 9999999999))
                email = f"noemail_{safe_phone}@hash.local"
            if not phone:
                phone = "0000000000"

            user = User(
                fid=generate_fid(),
                avatar_path="Not defined",
                name=name,
                game_username=game_username,
                parent_type="user",
                platform="dashboard",
            )
            db.session.add(user)
            db.session.flush()

            contact_info = ContactInfo(
                email=email,
                phone=phone,
                parent_id=user.id,
                parent_type="user"
            )
            user.contact_info = contact_info
            db.session.add(contact_info)

            # Optional metadata passthrough for upcoming recovery workflows.
            if whatsapp and not body.get("phone"):
                contact_info.phone = whatsapp

            db.session.commit()
            return jsonify({
                "success": True,
                "created": True,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "email": contact_info.email,
                    "phone": contact_info.phone,
                    "address": address or None,
                    "whatsapp_number": whatsapp or None,
                }
            }), 201

        table_name = f"VENDOR_{vendor_id}_DASHBOARD"
        vendor_id_int = int(vendor_id)
        user_ids = set()

        # Step 1: Get user_ids from vendor bookings table (if it exists)
        try:
            user_id_query = text(f"SELECT DISTINCT user_id FROM {table_name}")
            result = db.session.execute(user_id_query)
            user_ids.update([row[0] for row in result if row[0]])
        except Exception:
            # Dashboard table might not exist for new vendors yet.
            db.session.rollback()

        # Step 2: Include users from monthly credit accounts so newly onboarded
        # credit customers appear in selector even before first booking.
        credit_user_ids = (
            db.session.query(MonthlyCreditAccount.user_id)
            .filter(MonthlyCreditAccount.vendor_id == vendor_id_int)
            .distinct()
            .all()
        )
        user_ids.update([row[0] for row in credit_user_ids if row[0]])

        # Step 3: Include squad member user IDs mapped to this vendor's bookings.
        # Without this, users created through squad member rows won't appear
        # in the quick selector until they become a primary booking user.
        squad_user_ids = (
            db.session.query(BookingSquadMember.member_user_id)
            .join(Booking, Booking.id == BookingSquadMember.booking_id)
            .join(Transaction, Transaction.booking_id == Booking.id)
            .filter(
                Transaction.vendor_id == vendor_id_int,
                BookingSquadMember.member_user_id.isnot(None),
            )
            .distinct()
            .all()
        )
        user_ids.update([row[0] for row in squad_user_ids if row[0]])

        if not user_ids:
            return jsonify([]), 200

        # Step 4: Fetch User and ContactInfo
        users = User.query.filter(User.id.in_(list(user_ids))).all()

        user_list = []
        for user in users:
            contact = ContactInfo.query.filter_by(parent_id=user.id, parent_type="user").first()
            
            user_data = {
                "id": user.id,
                "name": user.name,
                "game_username": user.game_username,
                "avatar_path": user.avatar_path,
                "gender": user.gender,
                "dob": user.dob.isoformat() if user.dob else None,
                "email": contact.email if contact else None,
                "phone": contact.phone if contact else None
            }
            user_list.append(user_data)

        return jsonify(user_list), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error fetching user details: {e}")
        return jsonify({"error": str(e)}), 500

@booking_blueprint.route('/vendor/<string:vendor_id>/getConsoleStatus/<int:console_id>', methods=['GET'])
def get_console_status(vendor_id, console_id):
    """Retrieve the availability status of a specific console for a vendor."""
    try:
        table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"

        # Construct SQL to get console details
        sql = text(f"""
            SELECT vendor_id, console_id, game_id, is_available
            FROM {table_name}
            WHERE console_id = :console_id
        """)

        result = db.session.execute(sql, {'console_id': console_id}).fetchall()

        if not result:
            return jsonify({"message": "Console not found."}), 404

        consoles = [
            {
                "vendor_id": row.vendor_id,
                "console_id": row.console_id,
                "game_id": row.game_id,
                "is_available": row.is_available
            } for row in result
        ]

        return jsonify(consoles), 200

    except Exception as e:
        current_app.logger.error(f"Error retrieving console status: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500
    
@booking_blueprint.route('/jobs/render/create', methods=['POST'])
def create_render_one_off_job():
    """
    Create a one-off job in Render dashboard
    """
    try:
        api_key = os.getenv('RENDER_API_KEY' , 'rnd_bJpw79wtDkiZSy2DqD2AybGPjj5T')
        service_id = os.getenv('SERVICE_ID', 'srv-culflkl6l47c73dntal0')
        
        url = f"https://api.render.com/v1/services/{service_id}/jobs"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
        'startCommand': "PYTHONPATH=/app python -m app.jobs.release_slot"
        }
    
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 201:
            job_data = response.json()
            return jsonify({
                "message": "One-off job created successfully",
                "job_id": job_data.get('id'),
                "service_id": job_data.get('serviceId'),
                "start_command": job_data.get('startCommand')
            }), 201
        else:
            return jsonify({
                "error": "Failed to create one-off job",
                "details": response.text
            }), response.status_code
            
    except Exception as e:
        return jsonify({
            "error": "Failed to create one-off job",
            "details": str(e)
        }), 500

def now_utc():
    return datetime.now(timezone.utc)

def to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Defensive: treat naive as IST, then to UTC
        return IST.localize(dt).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)

@booking_blueprint.route("/release_slot_job", methods=["POST"])
def release_slot_controller():
    """
    Releases bookings stuck in 'pending_verified' that are older than 2 minutes.
    Uses Booking.created_at (IST-aware) and converts to UTC for comparison.
    """
    now = now_utc()
    two_minutes_ago_utc = now - timedelta(minutes=2)
    now_ist = now.astimezone(IST)
    two_minutes_ago_ist = two_minutes_ago_utc.astimezone(IST)

    # Optional: constrain to a recent window to keep scans lean
    # Set to None to disable.
    recent_window_hours = 6
    lower_bound_utc = now - timedelta(hours=recent_window_hours) if recent_window_hours else None
    lower_bound_ist = lower_bound_utc.astimezone(IST) if lower_bound_utc else None

    current_app.logger.info(
        "🔍 Start release scan | now_utc=%s | now_ist=%s | threshold_utc=%s | threshold_ist=%s | recent_window_hours=%s | lower_bound_utc=%s | lower_bound_ist=%s",
        now.isoformat(), now_ist.isoformat(),
        two_minutes_ago_utc.isoformat(), two_minutes_ago_ist.isoformat(),
        recent_window_hours, (lower_bound_utc.isoformat() if lower_bound_utc else None),
        (lower_bound_ist.isoformat() if lower_bound_ist else None),
    )

    try:
        # Quick metrics before fetching
        total_pending = db.session.query(func.count(Booking.id)).filter(Booking.status == 'pending_verified').scalar()
        current_app.logger.info("📊 Metrics: total_pending_verified=%s", total_pending)

        # Build base query
        q = (
            db.session.query(Booking)
            .options(
                joinedload(Booking.slot),
                joinedload(Booking.game)
            )
            .filter(Booking.status == 'pending_verified')
        )

        # Upper bound (safety) — created_at should not be in the future relative to now_ist
        q = q.filter(Booking.created_at <= now_ist)

        # Lower bound for performance if enabled
        if lower_bound_ist:
            q = q.filter(Booking.created_at >= lower_bound_ist)

        # Fetch candidates
        candidates = q.all()

        # Log candidate summary
        if candidates:
            min_created = min(b.created_at for b in candidates if b.created_at is not None)
            max_created = max(b.created_at for b in candidates if b.created_at is not None)
            current_app.logger.info(
                "📦 Candidates fetched: count=%s | created_at_min_ist=%s | created_at_max_ist=%s",
                len(candidates),
                (min_created.astimezone(IST).isoformat() if min_created else None),
                (max_created.astimezone(IST).isoformat() if max_created else None),
            )
        else:
            current_app.logger.info("📦 Candidates fetched: count=0 (no pending_verified within time window)")

        released = 0
        skipped = 0
        errors = []

        for booking in candidates:
            try:
                created_ist = booking.created_at  # should be tz-aware IST by model default
                created_utc = to_utc(created_ist)

                current_app.logger.debug(
                    "🔎 Candidate booking_id=%s user_id=%s status=%s created_ist=%s created_utc=%s",
                    booking.id, booking.user_id, booking.status,
                    (created_ist.isoformat() if created_ist else None),
                    (created_utc.isoformat() if created_utc else None),
                )

                if created_utc is None:
                    skipped += 1
                    current_app.logger.warning(
                        "⛔ Skip booking_id=%s: created_at is None or invalid", booking.id
                    )
                    continue

                # Decision: older than 2 minutes?
                if created_utc > two_minutes_ago_utc:
                    skipped += 1
                    current_app.logger.debug(
                        "⏭️ Skip booking_id=%s: age too young (created_utc=%s > threshold_utc=%s)",
                        booking.id, created_utc.isoformat(), two_minutes_ago_utc.isoformat()
                    )
                    continue

                # Format as YYYY-MM-DD (UTC)
                date_for_release_str = created_utc.strftime("%Y-%m-%d")
                vendor_id = getattr(booking.game, "vendor_id", None) if booking.game else None
                current_app.logger.info(
                    "⏳ Releasing id=%s user_id=%s slot_id=%s vendor_id=%s date_for_release=%s (UTC)",
                    booking.id, booking.user_id, booking.slot_id, vendor_id, date_for_release_str
                )

                # Perform release
                # If your release signature differs, adjust here.
                booked_date = getattr(booking, "booked_date", date_for_release_str)  # may not exist; log it for clarity
                current_app.logger.debug(
                    "🔧 Calling Booking.release_slot(slot_id=%s, booking_id=%s, booked_date=%s)",
                    booking.slot_id, booking.id, booked_date
                )
                BookingService.release_slot(booking.slot_id, booking.id, booked_date)

                released += 1
                current_app.logger.info("✅ Released booking_id=%s", booking.id)

            except Exception as item_err:
                db.session.rollback()
                errors.append({"booking_id": booking.id, "error": str(item_err)})
                current_app.logger.exception("❌ Release failed for booking_id=%s: %s", booking.id, item_err)

        # Clean up session after loop
        db.session.remove()

        current_app.logger.info(
            "🧾 Release summary | found=%s | released=%s | skipped=%s | errors=%s",
            len(candidates), released, skipped, len(errors)
        )

        status_code = 200 if not errors else 207
        return jsonify({
            "message": "Release scan complete",
            "found": len(candidates),
            "released": released,
            "skipped": skipped,
            "errors": errors
        }), status_code

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("❌ Release scan failed: %s", e)
        return jsonify({"message": "Release scan failed", "error": str(e)}), 500
    finally:
        db.session.remove()
        
# Add these endpoints to your booking_controller.py
@booking_blueprint.route('/pay-at-cafe/pending/<int:vendor_id>', methods=['GET'])
def get_pending_pay_at_cafe_bookings(vendor_id):
    """Get all pending pay-at-cafe bookings for a vendor"""
    try:
        current_app.logger.info(f"Fetching pending pay at cafe bookings for vendor {vendor_id}")
        
        
        # Updated query with proper timezone handling
        pending_bookings = db.session.query(
            Booking.id.label('bookingId'),
            Booking.slot_id.label('slotId'),
            Booking.user_id.label('userId'),
            Booking.game_id,
            Booking.created_at.label('emitted_at'),  # Direct access since it's not nullable
            Booking.squad_details.label('squad_details'),
            User.name.label('username'),
            Slot.start_time,
            Slot.end_time,
            AvailableGame.game_name,
            AvailableGame.single_slot_price,
            AvailableGame.vendor_id.label('vendorId')
        ).join(User, Booking.user_id == User.id)\
         .join(Slot, Booking.slot_id == Slot.id)\
         .join(AvailableGame, Booking.game_id == AvailableGame.id)\
         .filter(
             AvailableGame.vendor_id == vendor_id,
             Booking.status == 'pending_acceptance'
         ).order_by(Booking.created_at.desc()).all()

        notifications_by_key = {}
        for booking in pending_bookings:
            try:
                if booking.emitted_at:
                    emitted_at_iso = booking.emitted_at.isoformat()
                else:
                    emitted_at_iso = datetime.utcnow().isoformat()

                details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
                resolved_date = _coerce_date_value(details.get("booked_date") or details.get("book_date"))
                if not resolved_date:
                    resolved_date = booking.emitted_at.date() if booking.emitted_at else datetime.utcnow().date()
                booking_date = resolved_date.strftime('%Y-%m-%d')
                
                # Format time slot
                if booking.start_time and booking.end_time:
                    try:
                        start_time = booking.start_time.strftime('%I:%M %p')
                        end_time = booking.end_time.strftime('%I:%M %p')
                        time_slot = f"{start_time} - {end_time}"
                    except Exception:
                        time_slot = "N/A"
                else:
                    time_slot = "N/A"

                batch_id = details.get("batch_id") if isinstance(details, dict) else None
                key = str(batch_id) if batch_id else f"booking:{booking.bookingId}"

                if key not in notifications_by_key:
                    notifications_by_key[key] = {
                        "event_id": f"db-{booking.bookingId}",
                        "emitted_at": emitted_at_iso,
                        "bookingId": booking.bookingId,
                        "slotId": booking.slotId,
                        "vendorId": booking.vendorId,
                        "userId": booking.userId,
                        "username": booking.username or "Unknown User",
                        "game": {
                            "vendor_id": booking.vendorId,
                            "single_slot_price": booking.single_slot_price or 0,
                            "game_name": booking.game_name or "Unknown Game"
                        },
                        "game_id": booking.game_id,
                        "consoleType": "Console--1",
                        "consoleNumber": "-1",
                        "date": booking_date,
                        "slot_price": {
                            "vendor_id": booking.vendorId,
                            "single_slot_price": booking.single_slot_price or 0,
                            "game_name": booking.game_name or "Unknown Game"
                        },
                        "status": "pending_acceptance",
                        "statusLabel": "Pending",
                        "booking_status": "pending_acceptance",
                        "time": time_slot,
                        "processed_time": time_slot,
                        "batch_id": batch_id,
                        "booking_ids": [booking.bookingId],
                        "slot_ids": [booking.slotId],
                        "slot_count": 1,
                        "total_amount": float(booking.single_slot_price or 0),
                    }
                else:
                    existing = notifications_by_key[key]
                    existing["booking_ids"].append(booking.bookingId)
                    existing["slot_ids"].append(booking.slotId)
                    existing["slot_count"] = len(existing["booking_ids"])
                    existing["total_amount"] = round(float(existing["total_amount"]) + float(booking.single_slot_price or 0), 2)

            except Exception as item_error:
                current_app.logger.error(f"Error processing booking {booking.bookingId}: {item_error}")
                continue

        notifications = list(notifications_by_key.values())
        current_app.logger.info(f"Successfully processed {len(notifications)} pending bookings for vendor {vendor_id}")
        
        return jsonify({
            'success': True,
            'notifications': notifications,
            'count': len(notifications)
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching pending pay at cafe bookings: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@booking_blueprint.route('/pay-at-cafe/accept', methods=['POST'])
def accept_pay_at_cafe_booking():
    """Accept a pay-at-cafe booking and change status to confirmed"""
    try:
        data = request.get_json()
        booking_id = data.get('booking_id')
        vendor_id = data.get('vendor_id')

        current_app.logger.info(f"Accept pay at cafe booking: booking_id={booking_id}, vendor_id={vendor_id}")

        # Validation
        if not all([booking_id, vendor_id]):
            return jsonify({"success": False, "message": "booking_id and vendor_id are required"}), 400

        # Fetch booking
        booking = Booking.query.filter_by(id=booking_id).first()
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404

        if booking.status != 'pending_acceptance':
            return jsonify({"success": False, "message": "Booking is not pending acceptance"}), 400

        # Verify vendor ownership
        available_game = AvailableGame.query.filter_by(id=booking.game_id).first()
        if not available_game or available_game.vendor_id != vendor_id:
            return jsonify({"success": False, "message": "Unauthorized - This booking doesn't belong to your vendor"}), 403

        # Resolve batch scope (squad)
        details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
        batch_id = details.get("batch_id") if isinstance(details, dict) else None
        if batch_id:
            bookings_to_accept = (
                Booking.query
                .filter(Booking.status == 'pending_acceptance')
                .filter(Booking.squad_details["batch_id"].astext == str(batch_id))
                .all()
            )
        else:
            bookings_to_accept = [booking]

        # Get related objects
        vendor = Vendor.query.filter_by(id=vendor_id).first()
        actor = resolve_transaction_actor(request)
        if actor.get("source_channel") != "dashboard":
            actor["source_channel"] = "dashboard"

        # Create access code for confirmed booking(s)
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        accepted_booking_ids = []
        event_payloads = []
        for booking_row in bookings_to_accept:
            available_game = AvailableGame.query.filter_by(id=booking_row.game_id).first()
            if not available_game or available_game.vendor_id != vendor_id:
                continue

            user = User.query.filter_by(id=booking_row.user_id).first()
            slot_obj = Slot.query.filter_by(id=booking_row.slot_id).first()
            booked_date = resolve_booking_booked_date(booking_row)

            booking_row.status = 'confirmed'
            booking_row.updated_at = datetime.utcnow()
            booking_row.access_code_id = access_code_entry.id

            if booked_date:
                existing_details = booking_row.squad_details if isinstance(booking_row.squad_details, dict) else {}
                updated_details = dict(existing_details)
                updated_details["booked_date"] = booked_date.isoformat()
                booking_row.squad_details = updated_details

            _price = get_effective_price(vendor_id, available_game)
            transaction = Transaction(
                booking_id=booking_row.id,
                vendor_id=vendor_id,
                user_id=booking_row.user_id,
                user_name=user.name if user else "Unknown",
                original_amount=_price,
                amount=_price,
                discounted_amount=0,
                mode_of_payment="pay_at_cafe",
                payment_use_case="pay_at_cafe",
                booking_date=datetime.utcnow().date(),
                booked_date=booked_date,
                booking_time=datetime.utcnow().time(),
                booking_type="pay_at_cafe",
                settlement_status="pending",
                source_channel=actor["source_channel"],
                initiated_by_staff_id=actor.get("staff_id"),
                initiated_by_staff_name=actor.get("staff_name"),
                initiated_by_staff_role=actor.get("staff_role"),
                base_amount=_price,
                meals_amount=0.0,
                controller_amount=0.0,
                waive_off_amount=0.0,
            )
            db.session.add(transaction)
            db.session.flush()

            BookingService.insert_into_vendor_dashboard_table(transaction.id, -1)
            BookingService.insert_into_vendor_promo_table(transaction.id, -1)

            accepted_booking_ids.append(booking_row.id)

            if slot_obj and available_game and user:
                event_payloads.append(
                    build_booking_event_payload(
                        vendor_id=vendor_id,
                        booking_id=booking_row.id,
                        slot_id=booking_row.slot_id,
                        user_id=booking_row.user_id,
                        username=user.name,
                        game_id=booking_row.game_id,
                        game_name=available_game.game_name,
                        date_value=booked_date,
                        slot_price=available_game.single_slot_price,
                        start_time=slot_obj.start_time,
                        end_time=slot_obj.end_time,
                        console_id=None,
                        status="confirmed",
                        booking_status="upcoming",
                        squad_details=booking_row.squad_details or {},
                    )
                )

            # Send booking confirmation email
            if user and user.contact_info and slot_obj:
                booking_mail(
                    gamer_name=user.name,
                    gamer_phone=user.contact_info.phone,
                    gamer_email=user.contact_info.email,
                    cafe_name=vendor.cafe_name if vendor else "Gaming Cafe",
                    booking_date=datetime.utcnow().strftime("%Y-%m-%d"),
                    booked_for_date=booked_date.strftime("%Y-%m-%d"),
                    booking_details=[{
                        "booking_id": booking_row.id,
                        "slot_time": f"{slot_obj.start_time} - {slot_obj.end_time}"
                    }],
                    price_paid=_price
                )

        current_app.logger.info(
            "Pay-at-cafe batch accepted booking_ids=%s vendor_id=%s",
            accepted_booking_ids, vendor_id
        )
        
        # Emit acceptance notification via socket
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('pay_at_cafe_accepted', {
                'bookingId': booking_id,
                'vendorId': vendor_id,
                'bookingIds': accepted_booking_ids,
                'batch_id': batch_id,
                'userId': booking.user_id,
                'status': 'confirmed',
                'access_code': code,
                'message': 'Your booking has been accepted! Please visit the cafe with this confirmation.',
                'timestamp': datetime.utcnow().isoformat()
            })

        # Commit all changes
        db.session.commit()

        # Emit booking events so dashboards update upcoming list in real time
        socketio = current_app.extensions.get('socketio')
        for payload in event_payloads:
            try:
                emit_booking_event(
                    socketio,
                    event="booking",
                    data=payload,
                    vendor_id=vendor_id,
                )
            except Exception as emit_error:
                current_app.logger.warning(
                    "pay_at_cafe.accept emit failed booking_id=%s err=%s",
                    payload.get("booking_id") if isinstance(payload, dict) else None,
                    emit_error,
                )
        
        return jsonify({
            "success": True,
            "message": "Booking accepted and confirmed successfully!",
            "booking_id": booking_id,
            "booking_ids": accepted_booking_ids,
            "status": "confirmed",
            "batch_id": batch_id,
            "access_code": code
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error accepting pay at cafe booking: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to accept booking",
            "error": str(e)
        }), 500

@booking_blueprint.route('/pay-at-cafe/reject', methods=['POST'])
def reject_pay_at_cafe_booking():
    """Reject a pay-at-cafe booking and change status to cancelled"""
    try:
        data = request.get_json()
        booking_id = data.get('booking_id')
        vendor_id = data.get('vendor_id')
        rejection_reason = data.get('rejection_reason', 'No reason provided')

        current_app.logger.info(f"Reject pay at cafe booking: booking_id={booking_id}, vendor_id={vendor_id}, reason={rejection_reason}")

        # Validation
        if not all([booking_id, vendor_id]):
            return jsonify({"success": False, "message": "booking_id and vendor_id are required"}), 400

        # Fetch booking
        booking = Booking.query.filter_by(id=booking_id).first()
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404

        if booking.status != 'pending_acceptance':
            return jsonify({"success": False, "message": "Booking is not pending acceptance"}), 400

        # Verify vendor ownership
        available_game = AvailableGame.query.filter_by(id=booking.game_id).first()
        if not available_game or available_game.vendor_id != vendor_id:
            return jsonify({"success": False, "message": "Unauthorized - This booking doesn't belong to your vendor"}), 403

        details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
        batch_id = details.get("batch_id") if isinstance(details, dict) else None
        if batch_id:
            bookings_to_reject = (
                Booking.query
                .filter(Booking.status == 'pending_acceptance')
                .filter(Booking.squad_details["batch_id"].astext == str(batch_id))
                .all()
            )
        else:
            bookings_to_reject = [booking]

        vendor = Vendor.query.filter_by(id=vendor_id).first()
        rejected_booking_ids = []
        primary_user = None
        for booking_row in bookings_to_reject:
            available_game = AvailableGame.query.filter_by(id=booking_row.game_id).first()
            if not available_game or available_game.vendor_id != vendor_id:
                continue

            user = User.query.filter_by(id=booking_row.user_id).first()
            if primary_user is None:
                primary_user = user

            booked_date = resolve_booking_booked_date(booking_row)
            booking_row.status = 'cancelled'
            booking_row.updated_at = datetime.utcnow()

            try:
                BookingService.release_slot(booking_row.slot_id, booking_row.id, booked_date.strftime('%Y-%m-%d'))
                current_app.logger.info(f"Slot {booking_row.slot_id} released for cancelled booking {booking_row.id}")
            except Exception as e:
                current_app.logger.error(f"Failed to release slot for booking {booking_row.id}: {e}")

            rejected_booking_ids.append(booking_row.id)
        
        current_app.logger.info(
            "Pay-at-cafe batch rejected booking_ids=%s vendor_id=%s reason=%s",
            rejected_booking_ids, vendor_id, rejection_reason
        )
        
        # Emit rejection notification via socket
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('pay_at_cafe_rejected', {
                'bookingId': booking_id,
                'vendorId': vendor_id,
                'bookingIds': rejected_booking_ids,
                'batch_id': batch_id,
                'userId': booking.user_id,
                'status': 'cancelled',
                'reason': rejection_reason,
                'message': f'Your booking has been rejected by the vendor. Reason: {rejection_reason}',
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Send rejection email to customer
        if primary_user and primary_user.contact_info:
            reject_booking_mail(
                gamer_name=primary_user.name,
                gamer_email=primary_user.contact_info.email,
                cafe_name=vendor.cafe_name if vendor else "Gaming Cafe",
                reason=rejection_reason
            )
        
        # Commit changes
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Booking rejected and cancelled successfully!",
            "booking_id": booking_id,
            "booking_ids": rejected_booking_ids,
            "batch_id": batch_id,
            "status": "cancelled",
            "reason": rejection_reason
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error rejecting pay at cafe booking: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to reject booking",
            "error": str(e)
        }), 500

@booking_blueprint.route('/booking/<int:booking_id>/add-meals', methods=['POST', 'OPTIONS'])
def add_meals_to_booking(booking_id):
    """
    Add additional meals to an existing booking and update total amount
    """
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        return response
    
    try:
        current_app.logger.info(f"Adding meals to booking {booking_id}")
        data = request.get_json(silent=True) or {}
        
        # Get meals from request
        meals = data.get("meals", [])
        if not meals:
            return jsonify({"success": False, "message": "No meals provided"}), 400

        squad_member = data.get("squad_member") if isinstance(data.get("squad_member"), dict) else None
        squad_member_position = None
        squad_member_user_id = None
        squad_member_name = None
        if squad_member:
            try:
                squad_member_position = int(squad_member.get("member_position")) if squad_member.get("member_position") is not None else None
            except (TypeError, ValueError):
                squad_member_position = None
            try:
                squad_member_user_id = int(squad_member.get("member_user_id")) if squad_member.get("member_user_id") is not None else None
            except (TypeError, ValueError):
                squad_member_user_id = None
            squad_member_name = str(squad_member.get("name") or "").strip() or None
        
        # Validate booking exists and get vendor_id
        booking = db.session.query(Booking).filter_by(id=booking_id).first()
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404
        
        # Get vendor_id from the booking's game
        available_game = db.session.query(AvailableGame).filter_by(id=booking.game_id).first()
        if not available_game:
            return jsonify({"success": False, "message": "Game not found"}), 404
        
        vendor_id = available_game.vendor_id
        vendor = db.session.query(Vendor).filter_by(id=vendor_id).first()
        current_app.logger.info(f"Adding meals to booking {booking_id} for vendor {vendor_id}")
        
        squad_member_rows = (
            BookingSquadMember.query
            .filter_by(booking_id=booking_id)
            .order_by(BookingSquadMember.member_position.asc())
            .all()
        )

        if squad_member_rows:
            resolved_member = None
            if squad_member_user_id is not None:
                resolved_member = next(
                    (row for row in squad_member_rows if row.member_user_id == squad_member_user_id),
                    None,
                )
            if resolved_member is None and squad_member_position is not None:
                resolved_member = next(
                    (row for row in squad_member_rows if int(row.member_position or 0) == int(squad_member_position)),
                    None,
                )
            if resolved_member is None and squad_member_name:
                normalized_name = squad_member_name.strip().lower()
                resolved_member = next(
                    (row for row in squad_member_rows if str(row.name_snapshot or "").strip().lower() == normalized_name),
                    None,
                )
            if resolved_member is None:
                # Default to captain for squad bookings when the client omits or partially sends member info.
                resolved_member = next((row for row in squad_member_rows if bool(row.is_captain)), None) or squad_member_rows[0]

            squad_member_position = int(resolved_member.member_position or 0) or squad_member_position
            squad_member_user_id = int(resolved_member.member_user_id) if resolved_member.member_user_id else squad_member_user_id
            squad_member_name = str(resolved_member.name_snapshot or squad_member_name or "").strip() or squad_member_name
            squad_member = {
                "member_position": squad_member_position,
                "member_user_id": squad_member_user_id,
                "name": squad_member_name,
            }

        # Validate and process meals
        meal_details = []
        total_meals_cost = 0
        
        for meal in meals:
            menu_item_id = meal.get('menu_item_id')
            quantity = meal.get('quantity', 1)
            
            if not menu_item_id or quantity <= 0:
                return jsonify({"success": False, "message": "Invalid meal data provided"}), 400
            
            # Validate menu item
            menu_item = db.session.query(ExtraServiceMenu).join(
                ExtraServiceCategory
            ).filter(
                ExtraServiceMenu.id == menu_item_id,
                ExtraServiceCategory.vendor_id == vendor_id,
                ExtraServiceMenu.is_active == True,
                ExtraServiceCategory.is_active == True
            ).first()
            
            if not menu_item:
                return jsonify({
                    "success": False,
                    "message": f"Invalid or inactive menu item {menu_item_id} for this vendor"
                }), 400
            
            item_total = menu_item.price * quantity
            total_meals_cost += item_total
            
            meal_details.append({
                'menu_item': menu_item,
                'quantity': quantity,
                'unit_price': menu_item.price,
                'total_price': item_total
            })
            
            current_app.logger.info(f"Adding meal: {menu_item.name} x {quantity} = ₹{item_total}")
        
        # Create booking extra services for the existing booking
        for meal_detail in meal_details:
            booking_extra_service = BookingExtraService(
                booking_id=booking_id,
                menu_item_id=meal_detail['menu_item'].id,
                quantity=meal_detail['quantity'],
                unit_price=meal_detail['unit_price'],
                total_price=meal_detail['total_price']
            )
            db.session.add(booking_extra_service)
            current_app.logger.info(f"Created extra service for booking {booking_id}: {meal_detail['menu_item'].name}")

        # Persist member-level meal attribution inside squad_details ledger for audit/billing clarity.
        if squad_member:
            existing_squad_details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
            ledger = existing_squad_details.get("member_meal_ledger")
            if not isinstance(ledger, list):
                ledger = []
            ledger_entry = {
                "added_at": datetime.utcnow().isoformat(),
                "member_position": squad_member_position,
                "member_user_id": squad_member_user_id,
                "member_name": squad_member_name,
                "meals_total": float(total_meals_cost),
                "meals": [
                    {
                        "menu_item_id": int(detail["menu_item"].id),
                        "name": str(detail["menu_item"].name),
                        "quantity": int(detail["quantity"]),
                        "unit_price": float(detail["unit_price"]),
                        "total_price": float(detail["total_price"]),
                    }
                    for detail in meal_details
                ],
            }
            ledger.append(ledger_entry)
            updated_squad_details = dict(existing_squad_details)
            updated_squad_details["enabled"] = bool(updated_squad_details.get("enabled", True))
            updated_squad_details["member_meal_ledger"] = ledger
            booking.squad_details = updated_squad_details
        
        actor = resolve_transaction_actor(request)
        # Default behavior for in-session meal additions:
        # keep transaction pending and settle at end of session from Extra Payment overlay.
        settle_on_release = bool(data.get("settle_on_release", True))
        requested_mode = str(data.get("mode_of_payment") or "pending").strip().lower()
        if not settle_on_release and requested_mode in {"", "pending"}:
            return jsonify({
                "success": False,
                "message": "mode_of_payment is required when settle_on_release is false"
            }), 400
        mode_for_transaction = "pending" if settle_on_release else requested_mode
        payment_use_case = (
            "pay_at_cafe"
            if settle_on_release
            else normalize_payment_use_case(mode_for_transaction, actor["source_channel"])
        )
        settlement_status = "pending" if settle_on_release else resolve_settlement_status(payment_use_case)

        # Create additional transaction record for meal increment only.
        user = db.session.query(User).filter_by(id=booking.user_id).first()
        booking_date = datetime.utcnow().date()
        gst = calculate_gst_breakdown(vendor_id, total_meals_cost)
        
        additional_transaction = Transaction(
            booking_id=booking_id,
            vendor_id=vendor_id,
            user_id=booking.user_id,
            booked_date=booking_date,
            booking_date=datetime.utcnow().date(),
            booking_time=datetime.utcnow().time(),
            user_name=user.name if user else "Unknown User",
            original_amount=total_meals_cost,
            discounted_amount=0,
            amount=total_meals_cost,
            mode_of_payment=mode_for_transaction,
            payment_use_case=payment_use_case,
            booking_type="additional_meals",
            settlement_status=settlement_status,
            source_channel=actor["source_channel"],
            initiated_by_staff_id=actor["staff_id"],
            initiated_by_staff_name=actor["staff_name"],
            initiated_by_staff_role=actor["staff_role"],
            base_amount=0.0,
            meals_amount=total_meals_cost,
            controller_amount=0.0,
            waive_off_amount=0.0,
            taxable_amount=gst["taxable_amount"],
            gst_rate=gst["gst_rate"],
            cgst_amount=gst["cgst_amount"],
            sgst_amount=gst["sgst_amount"],
            igst_amount=gst["igst_amount"],
            total_with_tax=gst["total_with_tax"],
        )
        db.session.add(additional_transaction)
        
        # Commit database changes first
        db.session.commit()
        current_app.logger.info(f"✅ Database changes committed for booking {booking_id}")

        # Emit a payment update event for realtime dashboards.
        socketio = current_app.extensions.get('socketio')
        if socketio:
            payload = {
                "vendorId": int(vendor_id),
                "bookingId": int(booking_id),
                "slotId": int(booking.slot_id) if booking.slot_id else None,
                "userId": int(booking.user_id) if booking.user_id else None,
                "username": user.name if user else None,
                "game_id": int(booking.game_id) if booking.game_id else None,
                "date": resolve_booking_booked_date(booking).isoformat(),
                "event": "meals_added",
                "settle_on_release": bool(settle_on_release),
                "payment_use_case": payment_use_case,
                "settlement_status": settlement_status,
                "amount_added": float(total_meals_cost),
            }
            try:
                socketio.emit("booking_payment_update", payload, to=f"vendor_{int(vendor_id)}")
            except TypeError:
                socketio.emit("booking_payment_update", payload, room=f"vendor_{int(vendor_id)}")
        
        email_sent_to = None
        # ✅ NEW: Send email notification with meal details using dedicated function
        try:
            if user:
                contact_info = db.session.query(ContactInfo).filter_by(
                    parent_id=user.id, 
                    parent_type='user'
                ).first()
                
                slot = db.session.query(Slot).filter_by(id=booking.slot_id).first()
                
                if contact_info and contact_info.email:
                    # Prepare meal details for email
                    email_meal_details = []
                    for detail in meal_details:
                        email_meal_details.append({
                            'name': detail['menu_item'].name,
                            'quantity': detail['quantity'],
                            'unit_price': float(detail['unit_price']),
                            'total_price': float(detail['total_price'])
                        })
                    
                    summary_for_email = compute_booking_financial_summary(booking_id)
                    updated_total = float(summary_for_email["total_charged"])
                    
                    # Format slot time
                    if slot and slot.start_time and slot.end_time:
                        slot_time = f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}"
                    else:
                        slot_time = "N/A"
                    
                    # ✅ Use the dedicated meals_added_mail function
                    from services.mail_service import meals_added_mail
                    
                    meals_added_mail(
                        gamer_name=user.name,
                        gamer_email=contact_info.email,
                        cafe_name=vendor.cafe_name if vendor else "Gaming Cafe",
                        booking_id=booking.id,
                        slot_time=slot_time,
                        added_meals=email_meal_details,
                        meals_total=float(total_meals_cost),
                        updated_booking_total=updated_total,
                        booking_date=booking.created_at.strftime('%Y-%m-%d') if booking.created_at else datetime.utcnow().strftime('%Y-%m-%d')
                    )
                    
                    current_app.logger.info(f"✅ Meals added email sent successfully to {contact_info.email}")
                    email_sent_to = contact_info.email
                else:
                    current_app.logger.warning(f"⚠️ No email address found for user {user.id}")
        except Exception as email_error:
            # Don't fail the request if email fails - log and continue
            current_app.logger.error(f"❌ Failed to send email notification: {str(email_error)}")
            import traceback
            current_app.logger.error(f"Email error traceback: {traceback.format_exc()}")
        
        current_app.logger.info(f"✅ Successfully added {len(meal_details)} meals to booking {booking_id}, total cost: ₹{total_meals_cost}")
        summary = compute_booking_financial_summary(booking_id)
        
        # Return success response with all details
        return jsonify({
            "success": True,
            "message": "Meals added successfully",
            "booking_id": booking_id,
            "total_meals_cost": float(total_meals_cost),
            "squad_member": {
                "member_position": squad_member_position,
                "member_user_id": squad_member_user_id,
                "member_name": squad_member_name,
            } if squad_member else None,
            "payment_status": {
                "label": "Extra Payment Required" if summary["amount_due"] > 0 else "Settled",
                "amount_paid": summary["amount_paid"],
                "amount_due": summary["amount_due"],
                "total_charged": summary["total_charged"],
            },
            "added_meals": [
                {
                    "name": detail['menu_item'].name,
                    "category": detail['menu_item'].category.name,
                    "quantity": detail['quantity'],
                    "unit_price": float(detail['unit_price']),
                    "total_price": float(detail['total_price'])
                }
                for detail in meal_details
            ],
            "email_sent": email_sent_to,
            "financial_summary": summary
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'❌ Failed to add meals to booking {booking_id}: {str(e)}')
        import traceback
        current_app.logger.error(f'Traceback: {traceback.format_exc()}')
        return jsonify({
            "success": False,
            "message": "Failed to add meals",
            "error": str(e)
        }), 500


@booking_blueprint.route('/booking/<int:booking_id>/payment-summary', methods=['GET'])
def booking_payment_summary(booking_id):
    try:
        booking = Booking.query.filter_by(id=booking_id).first()
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404

        summary = compute_booking_financial_summary(booking_id)
        return jsonify({
            "success": True,
            "payment_status": {
                "label": "Extra Payment Required" if summary["amount_due"] > 0 else "Settled",
                "amount_paid": summary["amount_paid"],
                "amount_due": summary["amount_due"],
                "total_charged": summary["total_charged"],
            },
            "financial_summary": summary,
            "squad_member_meal_ledger": (
                booking.squad_details.get("member_meal_ledger", [])
                if isinstance(booking.squad_details, dict)
                else []
            ),
        }), 200
    except Exception as e:
        current_app.logger.error(f"Failed to build booking payment summary for {booking_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/booking/<int:booking_id>/settle-pending', methods=['POST'])
def settle_pending_booking_transactions(booking_id):
    """
    Settle pending end-of-session charges for a booking.
    By default settles only extra and additional_meals transactions.
    """
    try:
        body = request.get_json(silent=True) or {}
        mode = str(body.get("mode_of_payment") or "").strip().lower()
        waive_off_amount = float(body.get("waive_off_amount") or 0.0)
        if not mode:
            return jsonify({"success": False, "message": "mode_of_payment is required"}), 400

        booking = Booking.query.filter_by(id=booking_id).first()
        if not booking:
            return jsonify({"success": False, "message": "Booking not found"}), 404

        include_types = body.get("booking_types") or ["extra", "additional_meals", "pay_at_cafe"]
        include_types = [str(x).strip().lower() for x in include_types if str(x).strip()]
        if not include_types:
            include_types = ["extra", "additional_meals", "pay_at_cafe"]

        actor = resolve_transaction_actor(request)
        payment_use_case = normalize_payment_use_case(mode, actor["source_channel"])
        credit_account = None
        if payment_use_case == "monthly_credit":
            credit_account = MonthlyCreditAccount.query.filter_by(
                vendor_id=booking.game.vendor_id if booking.game else None,
                user_id=booking.user_id,
                is_active=True
            ).first()
            if not credit_account:
                return jsonify({
                    "success": False,
                    "message": "Monthly credit account not configured for this customer."
                }), 400

        pending_rows = (
            Transaction.query
            .filter(Transaction.booking_id == booking_id)
            .filter(func.lower(Transaction.booking_type).in_(include_types))
            .filter(or_(
                Transaction.settlement_status.is_(None),
                func.lower(Transaction.settlement_status).in_(["pending", "unpaid", "due"])
            ))
            .all()
        )

        pending_total = 0.0
        for tx in pending_rows:
            line_total = float(tx.total_with_tax or 0) if float(tx.total_with_tax or 0) > 0 else float(tx.amount or 0)
            pending_total += max(line_total, 0.0)

        applied_waive_off = min(max(waive_off_amount, 0.0), pending_total)
        if credit_account:
            projected_credit_charge = max(pending_total - applied_waive_off, 0.0)
            credit_limit_error = validate_monthly_credit_capacity(credit_account, projected_credit_charge)
            if credit_limit_error:
                return jsonify(credit_limit_error), 400

        # Keep discount auditable via a dedicated negative transaction.
        if applied_waive_off > 0:
            discount_tx = Transaction(
                booking_id=booking_id,
                vendor_id=(pending_rows[0].vendor_id if pending_rows else None),
                user_id=booking.user_id,
                booked_date=datetime.utcnow().date(),
                booking_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=(pending_rows[0].user_name if pending_rows else "Unknown User"),
                original_amount=applied_waive_off,
                discounted_amount=applied_waive_off,
                amount=-applied_waive_off,
                mode_of_payment=mode,
                payment_use_case=normalize_payment_use_case(mode, actor["source_channel"]),
                booking_type="settlement_waive_off",
                settlement_status="completed",
                source_channel=actor["source_channel"],
                initiated_by_staff_id=actor["staff_id"],
                initiated_by_staff_name=actor["staff_name"],
                initiated_by_staff_role=actor["staff_role"],
                base_amount=0.0,
                meals_amount=0.0,
                controller_amount=0.0,
                waive_off_amount=applied_waive_off,
                taxable_amount=0.0,
                gst_rate=0.0,
                cgst_amount=0.0,
                sgst_amount=0.0,
                igst_amount=0.0,
                total_with_tax=-applied_waive_off
            )
            db.session.add(discount_tx)

        settled_amount = 0.0
        settled_ids = []
        for tx in pending_rows:
            line_total = float(tx.total_with_tax or 0) if float(tx.total_with_tax or 0) > 0 else float(tx.amount or 0)
            settled_amount += line_total
            tx.mode_of_payment = mode
            tx.payment_use_case = payment_use_case
            tx.settlement_status = "pending" if payment_use_case == "monthly_credit" else "completed"
            tx.source_channel = actor["source_channel"]
            tx.initiated_by_staff_id = actor["staff_id"]
            tx.initiated_by_staff_name = actor["staff_name"]
            tx.initiated_by_staff_role = actor["staff_role"]
            settled_ids.append(tx.id)

        if credit_account and settled_amount > 0:
            due_date = compute_credit_due_date(
                datetime.utcnow().date(),
                credit_account.billing_cycle_day
            )
            db.session.add(
                MonthlyCreditLedger(
                    account_id=credit_account.id,
                    transaction_id=None,
                    entry_type="charge",
                    amount=max(settled_amount - applied_waive_off, 0.0),
                    description=f"Pending session settlement #{booking_id}",
                    booked_date=datetime.utcnow().date(),
                    due_date=due_date,
                    source_channel=actor["source_channel"],
                    staff_id=actor["staff_id"],
                    staff_name=actor["staff_name"],
                )
            )
            credit_account.outstanding_amount = float(credit_account.outstanding_amount or 0) + max(settled_amount - applied_waive_off, 0.0)

        db.session.commit()

        summary = compute_booking_financial_summary(booking_id)
        return jsonify({
            "success": True,
            "booking_id": booking_id,
            "settled_transaction_ids": settled_ids,
            "settled_count": len(settled_ids),
            "settled_amount": round(max(settled_amount - applied_waive_off, 0.0), 2),
            "applied_waive_off": round(applied_waive_off, 2),
            "payment_status": {
                "label": "Extra Payment Required" if summary["amount_due"] > 0 else "Settled",
                "amount_paid": summary["amount_paid"],
                "amount_due": summary["amount_due"],
                "total_charged": summary["total_charged"],
            },
            "financial_summary": summary
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to settle pending charges for booking {booking_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500



@booking_blueprint.route('/kiosk/next-slot/vendor/<int:vendor_id>', methods=['POST'])
def kiosk_book_next_slot(vendor_id):
    """
    Kiosk extension booking for the immediate next slot.

    Expected payload:
    {
      "bookingType": "extension",
      "consoleId": 84,
      "gameId": 47,
      "slotId": 841,
      "userId": 56,
      "paymentType": "pending"
    }
    """
    try:
        body = request.get_json(force=True) or {}
        console_id = int(body["consoleId"])
        game_id = int(body["GameId"]) if "GameId" in body else int(body["gameId"])
        slot_id = int(body["slotId"])
        user_id = int(body["userId"])
        payment_type = body.get("paymentType", "pending")

        # --- 0) Validate and prepare booking times ---
        slot_row = db.session.query(Slot).filter_by(id=slot_id).first()
        if not slot_row or slot_row.gaming_type_id != game_id:
            return jsonify({"success": False, "message": "Invalid slot for this game"}), 400

        booked_date = datetime.utcnow().date()
        start_dt = datetime.combine(booked_date, slot_row.start_time)
        end_dt = datetime.combine(booked_date, slot_row.end_time)

        vendor_slot_table = f"VENDOR_{vendor_id}_SLOT"
        console_table = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
        booking_table = f"VENDOR_{vendor_id}_DASHBOARD"

        # --- 1) Lock and update slot availability ---
        row = db.session.execute(text(f"""
            SELECT is_available, available_slot
            FROM {vendor_slot_table}
            WHERE vendor_id = :vid AND date = :dt AND slot_id = :sid
            FOR UPDATE
        """), {"vid": vendor_id, "dt": booked_date, "sid": slot_id}).mappings().first()

        if not row:
            return jsonify({"success": False, "message": "Vendor slot not found"}), 404
        if not row["is_available"] or int(row["available_slot"]) <= 0:
            return jsonify({"success": False, "message": "Slot unavailable"}), 409

        db.session.execute(text(f"""
            UPDATE {vendor_slot_table}
            SET available_slot = available_slot - 1,
                is_available = CASE WHEN available_slot - 1 > 0 THEN TRUE ELSE FALSE END
            WHERE vendor_id = :vid AND date = :dt AND slot_id = :sid
        """), {"vid": vendor_id, "dt": booked_date, "sid": slot_id})

        # --- 2) Lock and update console availability ---
        db.session.execute(text(f"""
            SELECT is_available
            FROM {console_table}
            WHERE console_id = :cid AND game_id = :gid
            FOR UPDATE
        """), {"cid": console_id, "gid": game_id})
        
        db.session.execute(text(f"""
            UPDATE {console_table}
            SET is_available = FALSE
            WHERE console_id = :cid AND game_id = :gid
        """), {"cid": console_id, "gid": game_id})

        # --- 3) Create booking record ---
        booking = Booking(
            slot_id=slot_id,
            game_id=game_id,
            user_id=user_id,
            status="confirmed"
        )
        db.session.add(booking)
        db.session.flush()
        new_book_id = booking.id

        # --- 4) Get user name for dashboard ---
        user = db.session.query(User).filter_by(id=user_id).first()
        username = user.name if user and user.name else "Unknown"

        # --- 5) Get single slot price (for frontend) ---
        #price_row = db.session.execute(text("""
        #   SELECT single_slot_price
        #     FROM available_games
        #    WHERE id = :gid
        #"""), {"gid": game_id}).fetchone()
        #single_price = int(price_row.single_slot_price) if price_row and price_row.single_slot_price else None
        
        available_game_obj = AvailableGame.query.filter_by(id=game_id).first()
        single_price = int(get_effective_price(vendor_id, available_game_obj)) if available_game_obj else None

        # --- 6) Insert into vendor dashboard ---
        db.session.execute(text(f"""
            INSERT INTO {booking_table}
                (book_id, game_id, date, start_time, end_time,
                 book_status, console_id, username, user_id, game_name,
                 status, extra_pay_status)
            VALUES
                (:bid, :gid, :dt, :st, :et, 'upcoming', NULL, :uname, :uid, :gname, TRUE, FALSE)
        """), {
            "bid": new_book_id,
            "gid": game_id,
            "dt": booked_date,
            "st": start_dt.time(),
            "et": end_dt.time(),
            "uname": username,
            "uid": user_id,
            "gname": "pc"
        })

        # --- 7) Mark booking as current and assign console ---
        db.session.execute(text(f"""
            UPDATE {booking_table}
            SET book_status = 'current', console_id = :cid
            WHERE book_id = :bid AND game_id = :gid
        """), {"cid": console_id, "bid": new_book_id, "gid": game_id})

        db.session.commit()

        # --- 8) Socket updates ---
        socketio = current_app.extensions.get('socketio')
        room = f"vendor_{vendor_id}"

        socketio.emit("current_slot", {
            "slot_id": slot_id,
            "book_id": new_book_id,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "status": "current",
            "console_id": console_id,
            "user_id": user_id,
            "username": username,
            "game_id": game_id,
            "date": booked_date.isoformat(),
            "single_slot_price": single_price
        }, room=room)

        remaining_row = db.session.execute(text(f"""
            SELECT COUNT(*) AS remaining
            FROM {console_table}
            WHERE game_id = :gid AND is_available = TRUE
        """), {"gid": game_id}).fetchone()
        remaining = int(remaining_row.remaining) if remaining_row else 0

        socketio.emit("console_availability", {
            "vendorId": vendor_id,
            "game_id": game_id,
            "console_id": console_id,
            "is_available": False,
            "remaining_available_for_game": remaining
        }, room=room)

        return jsonify({
            "success": True,
            "message": "Next slot booked and console assigned successfully",
            "booking_id": new_book_id,
            "slot_id": slot_id,
            "username": username,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "provisional": True
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("kiosk_book_next_slot error")
        return jsonify({"success": False, "message": "Server error", "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/slot-bookings', methods=['GET'])
def get_slot_bookings(vendor_id):
    """
    Get all bookings for specific slot(s) and date
    Query params: slot_ids (comma-separated), date (YYYY-MM-DD)
    """
    try:
        # Get query parameters
        slot_ids_param = request.args.get('slot_ids')  # e.g., "1,2,3"
        date_param = request.args.get('date')  # e.g., "2026-01-17"
        
        if not slot_ids_param or not date_param:
            return jsonify({
                'success': False,
                'message': 'slot_ids and date are required'
            }), 400
        
        # Parse slot IDs
        try:
            slot_ids = [int(sid.strip()) for sid in slot_ids_param.split(',')]
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid slot_ids format'
            }), 400
        
        # Parse date
        try:
            booking_date = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Use YYYY-MM-DD'
            }), 400
        
        current_app.logger.info(
            f"Fetching bookings for vendor={vendor_id} slots={slot_ids} date={booking_date}"
        )
        
        # Query bookings with all related data
        # ✅ FIXED: Changed ContactInfo.user_id to ContactInfo.parent_id
        bookings_query = db.session.query(Booking)\
            .join(Transaction, Transaction.booking_id == Booking.id)\
            .join(User, User.id == Booking.user_id)\
            .join(ContactInfo, (ContactInfo.parent_id == User.id) & (ContactInfo.parent_type == 'user'))\
            .outerjoin(BookingExtraService, BookingExtraService.booking_id == Booking.id)\
            .outerjoin(ExtraServiceMenu, ExtraServiceMenu.id == BookingExtraService.menu_item_id)\
            .filter(
                Booking.slot_id.in_(slot_ids),
                Transaction.booked_date == booking_date,
                Transaction.vendor_id == vendor_id,
                Booking.status.in_(['confirmed', 'checked_in', 'completed', 'pending_verified', 'pending_acceptance'])
            )\
            .options(
                joinedload(Booking.transaction),
                joinedload(Booking.slot),
                joinedload(Booking.booking_extra_services).joinedload(BookingExtraService.extra_service_menu),
                joinedload(Booking.squad_members)
            )\
            .distinct()\
            .all()
        
        current_app.logger.info(f"Found {len(bookings_query)} bookings")
        
        # Format response
        bookings_data = []
        for booking in bookings_query:
            # Get user details
            user = User.query.filter_by(id=booking.user_id).first()
            # ✅ FIXED: Changed user_id to parent_id and added parent_type filter
            contact_info = ContactInfo.query.filter_by(
                parent_id=user.id,
                parent_type='user'
            ).first() if user else None
            
            # Get meal selections
            meals = []
            for extra_service in booking.booking_extra_services:
                if extra_service.extra_service_menu:
                    meals.append({
                        'name': extra_service.extra_service_menu.name,
                        'quantity': extra_service.quantity,
                        'price': float(extra_service.unit_price),
                        'total': float(extra_service.total_price)
                    })
            
            # Format meal selection display
            meal_text = "No meal selected"
            if meals:
                meal_text = ", ".join([f"{m['quantity']}x {m['name']}" for m in meals])

            squad_details = booking.squad_details if isinstance(booking.squad_details, dict) else {}
            squad_member_rows = sorted(
                booking.squad_members or [],
                key=lambda m: int(getattr(m, "member_position", 9999) or 9999)
            )
            squad_members = [
                {
                    "id": int(member.id),
                    "member_user_id": int(member.member_user_id) if member.member_user_id else None,
                    "member_position": int(member.member_position),
                    "is_captain": bool(member.is_captain),
                    "name": member.name_snapshot,
                    "phone": member.phone_snapshot,
                }
                for member in squad_member_rows
            ]
            squad_player_count = int(
                squad_details.get("player_count")
                or squad_details.get("playerCount")
                or (len(squad_members) if squad_members else 1)
            )
            squad_enabled = bool(squad_details.get("enabled")) or squad_player_count > 1
            
            bookings_data.append({
                'booking_id': booking.id,
                'booking_fid': f"#BK-{booking.id}",
                'customer_name': user.name if user else "Unknown",
                'customer_email': contact_info.email if contact_info else "N/A",
                'customer_phone': contact_info.phone if contact_info else "N/A",
                'status': booking.status,
                'meal_selection': meal_text,
                'meals': meals,
                'slot_id': booking.slot_id,
                'booking_mode': booking.booking_mode,
                'created_at': booking.created_at.isoformat() if booking.created_at else None,
                'amount_paid': float(booking.transaction.amount) if booking.transaction else 0,
                'booking_date': booking.transaction.booked_date.isoformat() if booking.transaction and booking.transaction.booked_date else booking_date.isoformat(),
                'slot_start_time': booking.slot.start_time.strftime('%I:%M %p') if booking.slot and booking.slot.start_time else None,
                'slot_end_time': booking.slot.end_time.strftime('%I:%M %p') if booking.slot and booking.slot.end_time else None,
                'squad_enabled': squad_enabled,
                'squad_player_count': max(1, squad_player_count),
                'squad_members': squad_members,
                'squad_details': squad_details,
            })
        
        return jsonify({
            'success': True,
            'bookings': bookings_data,
            'count': len(bookings_data)
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching slot bookings: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to fetch bookings',
            'error': str(e)
        }), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/tax-profile', methods=['GET', 'PUT'])
def vendor_tax_profile(vendor_id):
    try:
        profile = VendorTaxProfile.query.filter_by(vendor_id=vendor_id).first()

        if request.method == 'GET':
            if not profile:
                return jsonify({
                    "success": True,
                    "profile": {
                        "vendor_id": vendor_id,
                        "gst_registered": False,
                        "gst_enabled": False,
                        "gst_rate": 18.0,
                        "tax_inclusive": False,
                    }
                }), 200
            return jsonify({"success": True, "profile": profile.to_dict()}), 200

        body = request.get_json(silent=True) or {}
        if not profile:
            profile = VendorTaxProfile(vendor_id=vendor_id)
            db.session.add(profile)

        profile.gst_registered = bool(body.get("gst_registered", profile.gst_registered))
        profile.gstin = body.get("gstin", profile.gstin)
        profile.legal_name = body.get("legal_name", profile.legal_name)
        profile.state_code = body.get("state_code", profile.state_code)
        profile.place_of_supply_state_code = body.get("place_of_supply_state_code", profile.place_of_supply_state_code)
        profile.gst_enabled = bool(body.get("gst_enabled", profile.gst_enabled))
        profile.gst_rate = float(body.get("gst_rate", profile.gst_rate or 18.0))
        profile.tax_inclusive = bool(body.get("tax_inclusive", profile.tax_inclusive))

        db.session.commit()
        return jsonify({"success": True, "profile": profile.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Tax profile update failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/time-wallet/<int:user_id>', methods=['GET'])
def get_time_wallet(vendor_id, user_id):
    try:
        account = TimeWalletAccount.query.filter_by(vendor_id=vendor_id, user_id=user_id).first()
        if not account:
            return jsonify({
                "success": True,
                "wallet": {
                    "vendor_id": vendor_id,
                    "user_id": user_id,
                    "balance_minutes": 0,
                    "balance_amount": 0,
                },
                "ledger": []
            }), 200

        rows = TimeWalletLedger.query.filter_by(account_id=account.id).order_by(TimeWalletLedger.created_at.desc()).limit(100).all()
        return jsonify({
            "success": True,
            "wallet": {
                "vendor_id": vendor_id,
                "user_id": user_id,
                "balance_minutes": int(account.balance_minutes or 0),
                "balance_amount": float(account.balance_amount or 0),
                "expires_at": account.expires_at.isoformat() if account.expires_at else None
            },
            "ledger": [
                {
                    "id": r.id,
                    "entry_type": r.entry_type,
                    "minutes": r.minutes,
                    "amount": float(r.amount or 0),
                    "description": r.description,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "booking_id": r.booking_id,
                    "transaction_id": r.transaction_id
                } for r in rows
            ]
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/time-wallet/credit-unused', methods=['POST'])
def credit_unused_slots_to_wallet(vendor_id):
    """
    Credit unused booked slots to user's time wallet.
    Body: { "user_id": 1, "booking_ids": [11,12], "description": "Early checkout" }
    """
    try:
        body = request.get_json(silent=True) or {}
        user_id = int(body.get("user_id"))
        booking_ids = body.get("booking_ids") or []
        description = body.get("description", "Unused slot carry-forward")

        if not booking_ids:
            return jsonify({"success": False, "message": "booking_ids required"}), 400

        account = TimeWalletAccount.query.filter_by(vendor_id=vendor_id, user_id=user_id).first()
        if not account:
            account = TimeWalletAccount(vendor_id=vendor_id, user_id=user_id, balance_minutes=0, balance_amount=0.0)
            db.session.add(account)
            db.session.flush()

        actor = resolve_transaction_actor(request)
        credited_minutes = 0
        credited_amount = 0.0

        for booking_id in booking_ids:
            booking = Booking.query.filter_by(id=booking_id, user_id=user_id).first()
            if not booking or not booking.slot_id:
                continue

            game = AvailableGame.query.filter_by(id=booking.game_id, vendor_id=vendor_id).first()
            if not game:
                continue

            slot = Slot.query.filter_by(id=booking.slot_id).first()
            slot_minutes = calculate_slot_minutes(slot)
            if slot_minutes <= 0:
                continue

            slot_amount = float(get_effective_price(vendor_id, game))
            account.balance_minutes = int(account.balance_minutes or 0) + slot_minutes
            account.balance_amount = float(account.balance_amount or 0) + slot_amount
            credited_minutes += slot_minutes
            credited_amount += slot_amount

            booking.status = "wallet_credited"

            db.session.add(
                TimeWalletLedger(
                    account_id=account.id,
                    booking_id=booking.id,
                    entry_type="credit",
                    minutes=slot_minutes,
                    amount=slot_amount,
                    description=description,
                    source_channel=actor["source_channel"],
                    staff_id=actor["staff_id"],
                    staff_name=actor["staff_name"],
                )
            )

        db.session.commit()
        return jsonify({
            "success": True,
            "credited_minutes": credited_minutes,
            "credited_amount": round(credited_amount, 2),
            "wallet_balance_minutes": int(account.balance_minutes or 0),
            "wallet_balance_amount": float(account.balance_amount or 0),
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to credit time wallet: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/monthly-credit/accounts', methods=['GET', 'PUT'])
def monthly_credit_accounts(vendor_id):
    try:
        if request.method == 'GET':
            rows = MonthlyCreditAccount.query.filter_by(vendor_id=vendor_id).all()
            return jsonify({
                "success": True,
                "accounts": [
                    {
                        "id": r.id,
                        "vendor_id": r.vendor_id,
                        "user_id": r.user_id,
                        "credit_limit": float(r.credit_limit or 0),
                        "outstanding_amount": float(r.outstanding_amount or 0),
                        "billing_cycle_day": r.billing_cycle_day,
                        "grace_days": r.grace_days,
                        "is_active": r.is_active,
                        "notes": r.notes,
                        "customer_name": r.customer_name,
                        "whatsapp_number": r.whatsapp_number,
                        "phone_number": r.phone_number,
                        "email": r.email,
                        "address_line1": r.address_line1,
                        "address_line2": r.address_line2,
                        "city": r.city,
                        "state": r.state,
                        "pincode": r.pincode,
                        "id_proof_type": r.id_proof_type,
                        "id_proof_number": r.id_proof_number,
                    } for r in rows
                ]
            }), 200

        body = request.get_json(silent=True) or {}
        user_id = int(body.get("user_id"))
        account = MonthlyCreditAccount.query.filter_by(vendor_id=vendor_id, user_id=user_id).first()
        if not account:
            account = MonthlyCreditAccount(vendor_id=vendor_id, user_id=user_id)
            db.session.add(account)

        account.credit_limit = float(body.get("credit_limit", account.credit_limit or 0))
        account.billing_cycle_day = int(body.get("billing_cycle_day", account.billing_cycle_day or 1))
        account.grace_days = int(body.get("grace_days", account.grace_days or 5))
        account.is_active = bool(body.get("is_active", True))
        account.notes = body.get("notes", account.notes)
        account.customer_name = body.get("customer_name", account.customer_name)
        account.whatsapp_number = body.get("whatsapp_number", account.whatsapp_number)
        account.phone_number = body.get("phone_number", account.phone_number)
        account.email = body.get("email", account.email)
        account.address_line1 = body.get("address_line1", account.address_line1)
        account.address_line2 = body.get("address_line2", account.address_line2)
        account.city = body.get("city", account.city)
        account.state = body.get("state", account.state)
        account.pincode = body.get("pincode", account.pincode)
        account.id_proof_type = body.get("id_proof_type", account.id_proof_type)
        account.id_proof_number = body.get("id_proof_number", account.id_proof_number)

        db.session.commit()
        return jsonify({"success": True, "account_id": account.id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/monthly-credit/statement/<int:user_id>', methods=['GET'])
def monthly_credit_statement(vendor_id, user_id):
    try:
        account = MonthlyCreditAccount.query.filter_by(vendor_id=vendor_id, user_id=user_id).first()
        if not account:
            return jsonify({"success": False, "message": "No monthly credit account"}), 404

        rows = MonthlyCreditLedger.query.filter_by(account_id=account.id).order_by(MonthlyCreditLedger.created_at.desc()).limit(500).all()
        transaction_ids = [r.transaction_id for r in rows if r.transaction_id]
        tx_map = {}
        if transaction_ids:
            tx_rows = (
                Transaction.query
                .filter(Transaction.id.in_(transaction_ids))
                .all()
            )
            tx_map = {t.id: t for t in tx_rows}

        return jsonify({
            "success": True,
            "account": {
                "credit_limit": float(account.credit_limit or 0),
                "outstanding_amount": float(account.outstanding_amount or 0),
                "billing_cycle_day": account.billing_cycle_day,
                "grace_days": account.grace_days,
                "customer_name": account.customer_name,
                "whatsapp_number": account.whatsapp_number,
                "phone_number": account.phone_number,
                "email": account.email,
                "address_line1": account.address_line1,
                "address_line2": account.address_line2,
                "city": account.city,
                "state": account.state,
                "pincode": account.pincode,
                "id_proof_type": account.id_proof_type,
                "id_proof_number": account.id_proof_number,
            },
            "entries": [
                {
                    "id": r.id,
                    "entry_type": r.entry_type,
                    "amount": float(r.amount or 0),
                    "description": r.description,
                    "booked_date": r.booked_date.isoformat() if r.booked_date else None,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "transaction_id": r.transaction_id,
                    "source_channel": r.source_channel,
                    "staff_id": r.staff_id,
                    "staff_name": r.staff_name,
                    "mode_of_payment": tx_map.get(r.transaction_id).mode_of_payment if r.transaction_id in tx_map else None,
                    "payment_use_case": tx_map.get(r.transaction_id).payment_use_case if r.transaction_id in tx_map else None,
                    "booking_type": tx_map.get(r.transaction_id).booking_type if r.transaction_id in tx_map else None,
                } for r in rows
            ]
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/monthly-credit/settle', methods=['POST'])
def settle_monthly_credit(vendor_id):
    """
    Settle monthly credit outstanding at month-end.
    Body: { "user_id": 1, "amount": 5000, "mode_of_payment": "UPI" }
    """
    try:
        body = request.get_json(silent=True) or {}
        user_id = int(body.get("user_id"))
        amount = float(body.get("amount", 0))
        mode = str(body.get("mode_of_payment", "UPI"))
        if amount <= 0:
            return jsonify({"success": False, "message": "amount must be > 0"}), 400

        account = MonthlyCreditAccount.query.filter_by(vendor_id=vendor_id, user_id=user_id, is_active=True).first()
        if not account:
            return jsonify({"success": False, "message": "Monthly credit account not found"}), 404

        user = User.query.filter_by(id=user_id).first()
        actor = resolve_transaction_actor(request)

        transaction = Transaction(
            booking_id=None,
            vendor_id=vendor_id,
            user_id=user_id,
            booked_date=datetime.utcnow().date(),
            booking_date=datetime.utcnow().date(),
            booking_time=datetime.utcnow().time(),
            user_name=user.name if user else "Unknown",
            original_amount=amount,
            discounted_amount=0.0,
            amount=amount,
            mode_of_payment=mode,
            payment_use_case=normalize_payment_use_case(mode, actor["source_channel"]),
            booking_type="monthly_credit_settlement",
            settlement_status="completed",
            source_channel=actor["source_channel"],
            initiated_by_staff_id=actor["staff_id"],
            initiated_by_staff_name=actor["staff_name"],
            initiated_by_staff_role=actor["staff_role"],
            base_amount=0.0,
            meals_amount=0.0,
            controller_amount=0.0,
            waive_off_amount=0.0,
            taxable_amount=0.0,
            gst_rate=0.0,
            cgst_amount=0.0,
            sgst_amount=0.0,
            igst_amount=0.0,
            total_with_tax=amount
        )
        db.session.add(transaction)
        db.session.flush()

        db.session.add(
            MonthlyCreditLedger(
                account_id=account.id,
                transaction_id=transaction.id,
                entry_type="payment",
                amount=amount,
                description="Month-end settlement",
                booked_date=datetime.utcnow().date(),
                due_date=None,
                source_channel=actor["source_channel"],
                staff_id=actor["staff_id"],
                staff_name=actor["staff_name"],
            )
        )

        account.outstanding_amount = max(0.0, float(account.outstanding_amount or 0) - amount)
        db.session.commit()

        return jsonify({
            "success": True,
            "transaction_id": transaction.id,
            "remaining_outstanding": float(account.outstanding_amount or 0),
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Monthly settlement failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
