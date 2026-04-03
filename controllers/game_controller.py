from flask import Blueprint, jsonify, request
from services.booking_service import BookingService
from models.availableGame import AvailableGame
from models.availableGame import available_game_console
from models.console import Console
from db.extensions import db
from models.openingDays import OpeningDay
from datetime import datetime
from flask_cors import cross_origin
import time
import os
from threading import Lock
from sqlalchemy import func
from services.console_catalog_service import (
    get_merged_console_catalog,
    resolve_console_capabilities,
    normalize_console_slug,
    get_vendor_console_overrides,
    upsert_vendor_console_override,
    set_vendor_console_override_active,
)


game_blueprint = Blueprint('game', __name__)
_GAMES_BY_VENDOR_CACHE = {}
_GAMES_BY_VENDOR_TTL_SECONDS = int(os.getenv("GAMES_BY_VENDOR_CACHE_TTL_SEC", "120"))
_GAMES_BY_VENDOR_CACHE_MAX_ITEMS = 1000
_GAMES_BY_VENDOR_CACHE_LOCK = Lock()


def _games_cache_get(cache_key, now_ts):
    with _GAMES_BY_VENDOR_CACHE_LOCK:
        item = _GAMES_BY_VENDOR_CACHE.get(cache_key)
        if not item:
            return None
        if (now_ts - item["ts"]) >= _GAMES_BY_VENDOR_TTL_SECONDS:
            _GAMES_BY_VENDOR_CACHE.pop(cache_key, None)
            return None
        return item["payload"]


def _games_cache_set(cache_key, payload, now_ts):
    with _GAMES_BY_VENDOR_CACHE_LOCK:
        if len(_GAMES_BY_VENDOR_CACHE) >= _GAMES_BY_VENDOR_CACHE_MAX_ITEMS:
            _GAMES_BY_VENDOR_CACHE.clear()
        _GAMES_BY_VENDOR_CACHE[cache_key] = {"ts": now_ts, "payload": payload}

# Get all available games
@game_blueprint.route('/games', methods=['GET'])
def get_all_games():
    games = AvailableGame.query.all()
    return jsonify([{
        "id": game.id,
        "game_name": game.game_name,
        "total_slots": game.total_slot,
        "single_slot_price": game.single_slot_price
    } for game in games])


@game_blueprint.route('/games/vendor/<int:vendor_id>', methods=['GET'])
def get_games_by_vendor_id(vendor_id):
    started_at = time.perf_counter()
    now = time.time()
    today_dt = datetime.now()
    cache_key = f"{vendor_id}:{today_dt.date().isoformat()}"
    cached_payload = _games_cache_get(cache_key, now)
    if cached_payload is not None:
        response = jsonify(cached_payload)
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
        return response, 200

    def _normalize_day_token(day_value: str) -> str:
        token = (day_value or "").strip().lower()
        mapping = {
            "monday": "mon",
            "mon": "mon",
            "tuesday": "tue",
            "tue": "tue",
            "tues": "tue",
            "wednesday": "wed",
            "wed": "wed",
            "thursday": "thu",
            "thu": "thu",
            "thurs": "thu",
            "friday": "fri",
            "fri": "fri",
            "saturday": "sat",
            "sat": "sat",
            "sunday": "sun",
            "sun": "sun",
        }
        return mapping.get(token, token)

    today = _normalize_day_token(today_dt.strftime('%a').lower())
    day_aliases = {today}

    opening_days = (
        OpeningDay.query
        .with_entities(OpeningDay.day)
        .filter_by(vendor_id=vendor_id, is_open=True)
        .all()
    )
    open_days = {_normalize_day_token(row.day) for row in opening_days}
    is_shop_open_today = (not open_days) or bool(day_aliases & open_days)

    games = (
        AvailableGame.query
        .with_entities(
            AvailableGame.id,
            AvailableGame.game_name,
            AvailableGame.total_slot,
            AvailableGame.single_slot_price
        )
        .filter_by(vendor_id=vendor_id)
        .all()
    )

    catalog = get_merged_console_catalog(vendor_id=vendor_id)
    games_by_slug = {}
    for game in games:
        slug = normalize_console_slug(game.game_name or "")
        games_by_slug[slug] = game

    vendor_console_counts = (
        db.session.query(Console.console_type, func.count(Console.id))
        .filter(Console.vendor_id == vendor_id)
        .group_by(Console.console_type)
        .all()
    )
    inventory_by_slug = {}
    for console_type, count in vendor_console_counts:
        slug = normalize_console_slug(console_type or "")
        inventory_by_slug[slug] = inventory_by_slug.get(slug, 0) + int(count or 0)

    if not games and not inventory_by_slug:
        payload = {
            "message": "No games found for this vendor",
            "shop_open": is_shop_open_today,
            "game_count": 0
        }
        _games_cache_set(cache_key, payload, now)
        response = jsonify(payload)
        response.headers["X-Cache"] = "MISS"
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
        return response, 200

    open_days_list = [row.day for row in opening_days]
    catalog_entries = []
    for entry in catalog:
        slug = normalize_console_slug(entry.get("slug") or "")
        linked_game = games_by_slug.get(slug)
        catalog_entries.append({
            "console_slug": slug,
            "console_display_name": entry.get("display_name") or (linked_game.game_name if linked_game else slug.replace("_", " ").title()),
            "icon": entry.get("icon") or "Monitor",
            "family": entry.get("family") or "other",
            "input_mode": entry.get("input_mode") or "controller",
            "supports_multiplayer": bool(entry.get("supports_multiplayer")),
            "default_capacity": int(entry.get("default_capacity") or 1),
            "controller_policy": entry.get("controller_policy") or "none",
            "inventory_count": int(inventory_by_slug.get(slug, 0)),
            "has_game_pricing": bool(linked_game),
            "available_game_id": int(linked_game.id) if linked_game else None,
            "bookable": bool(linked_game),
        })

    missing_catalog_pricing = [
        c for c in catalog_entries if c["inventory_count"] > 0 and not c["has_game_pricing"]
    ]

    payload = {
        "games": [{
            "id": game.id,
            "game_name": game.game_name,
            "total_slots": game.total_slot,
            "single_slot_price": game.single_slot_price,
            "opening_days": open_days_list
        } for game in games],
        "shop_open": is_shop_open_today,
        "game_count": len(games),
        "console_types": catalog_entries,
        "missing_catalog_pricing_count": len(missing_catalog_pricing),
        "missing_catalog_pricing": missing_catalog_pricing,
    }
    _games_cache_set(cache_key, payload, now)
    response = jsonify(payload)
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started_at) * 1000:.2f}"
    return response, 200

# Create a new booking for a game
@game_blueprint.route('/bookings', methods=['POST'])
def create_booking():
    data = request.get_json()
    try:
        booking = BookingService.create_booking(data)
        return jsonify({
            "id": booking.id,
            "user_id": booking.user_id,
            "game_id": booking.game_id
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

# Get all bookings for a user
@game_blueprint.route('/bookings/user/<int:user_id>', methods=['GET'])
def get_user_bookings(user_id):
    bookings = BookingService.get_user_bookings(user_id)
    return jsonify([{
        "booking_id": booking.id,
        "user_id": booking.user_id,
        "game_id": booking.game_id
    } for booking in bookings])

# Cancel a booking
@game_blueprint.route('/bookings/<int:booking_id>', methods=['DELETE'])
def cancel_booking(booking_id):
    try:
        BookingService.cancel_booking(booking_id)
        return jsonify({"message": "Booking canceled successfully."})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@game_blueprint.route('/getAllConsole/vendor/<int:vendor_id>', methods=['GET'])
@cross_origin(origins="*")
def get_all_console_by_vendor_id(vendor_id):
    # Return only console types that are actually mapped to vendor consoles.
    games = (
        db.session.query(
            AvailableGame.id,
            AvailableGame.game_name,
            AvailableGame.single_slot_price,
            func.count(func.distinct(Console.id)).label("console_count"),
        )
        .join(
            available_game_console,
            available_game_console.c.available_game_id == AvailableGame.id,
        )
        .join(Console, Console.id == available_game_console.c.console_id)
        .filter(
            AvailableGame.vendor_id == vendor_id,
            Console.vendor_id == vendor_id,
        )
        .group_by(AvailableGame.id, AvailableGame.game_name, AvailableGame.single_slot_price)
        .having(func.count(func.distinct(Console.id)) > 0)
        .all()
    )

    catalog = get_merged_console_catalog(vendor_id=vendor_id)
    capability_by_slug = {str(item.get("slug")): item for item in catalog}

    # If no games found, return an appropriate message
    if not games:
        return jsonify({
            "message": "No games found for this vendor",
            "shop_open": True,
            "game_count": 0
        }), 200

    # Return the game details along with the vendor's open days in JSON format
    items = []
    for row in games:
        normalized_slug = normalize_console_slug(row.game_name or "")
        capabilities = capability_by_slug.get(normalized_slug) or resolve_console_capabilities(vendor_id, row.game_name)
        items.append(
            {
                "id": row.id,
                "console_name": row.game_name,
                "console_slug": capabilities.get("slug", normalized_slug or "unknown"),
                "console_display_name": capabilities.get("display_name", row.game_name),
                "console_price": row.single_slot_price,
                "console_count": int(row.console_count or 0),
                "icon": capabilities.get("icon") or "Monitor",
                "family": capabilities.get("family") or "other",
                "input_mode": capabilities.get("input_mode") or "controller",
                "supports_multiplayer": bool(capabilities.get("supports_multiplayer")),
                "default_capacity": int(capabilities.get("default_capacity") or 1),
                "controller_policy": capabilities.get("controller_policy") or "none",
                "is_active": True,
            }
        )

    return jsonify({
        "games": items,
        "catalog": catalog,
    })


@game_blueprint.route('/console-types/vendor/<int:vendor_id>', methods=['GET'])
@cross_origin(origins="*")
def get_console_types_by_vendor(vendor_id):
    include_inactive = str(request.args.get("include_inactive", "false")).strip().lower() == "true"
    return jsonify(
        {
            "vendor_id": int(vendor_id),
            "console_types": get_merged_console_catalog(vendor_id=vendor_id, include_inactive=include_inactive),
        }
    ), 200


@game_blueprint.route('/console-types', methods=['GET'])
@cross_origin(origins="*")
def get_console_types():
    vendor_id = request.args.get("vendor_id")
    include_inactive = str(request.args.get("include_inactive", "false")).strip().lower() == "true"
    resolved_vendor_id = None
    if vendor_id is not None:
        try:
            resolved_vendor_id = int(vendor_id)
        except (TypeError, ValueError):
            return jsonify({"message": "vendor_id must be a valid integer"}), 400

    return jsonify(
        {
            "vendor_id": resolved_vendor_id,
            "console_types": get_merged_console_catalog(
                vendor_id=resolved_vendor_id,
                include_inactive=include_inactive,
            ),
        }
    ), 200


@game_blueprint.route('/console-types/vendor/<int:vendor_id>/overrides', methods=['GET'])
@cross_origin(origins="*")
def get_console_type_overrides(vendor_id):
    include_inactive = str(request.args.get("include_inactive", "false")).strip().lower() == "true"
    return jsonify(
        {
            "vendor_id": int(vendor_id),
            "overrides": get_vendor_console_overrides(vendor_id=vendor_id, include_inactive=include_inactive),
            "console_types": get_merged_console_catalog(vendor_id=vendor_id, include_inactive=include_inactive),
        }
    ), 200


@game_blueprint.route('/console-types/vendor/<int:vendor_id>/overrides', methods=['POST'])
@cross_origin(origins="*")
def create_or_update_console_type_override(vendor_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = upsert_vendor_console_override(vendor_id=vendor_id, payload=payload)
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "vendor_id": int(vendor_id),
                "override": row,
                "console_types": get_merged_console_catalog(vendor_id=vendor_id),
            }
        ), 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Failed to save override: {exc}"}), 500


@game_blueprint.route('/console-types/vendor/<int:vendor_id>/overrides/<string:slug>', methods=['DELETE'])
@cross_origin(origins="*")
def deactivate_console_type_override(vendor_id, slug):
    try:
        row = set_vendor_console_override_active(vendor_id=vendor_id, slug=slug, is_active=False)
        if row is None:
            return jsonify({"success": False, "message": "Override not found"}), 404
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "vendor_id": int(vendor_id),
                "override": row,
                "console_types": get_merged_console_catalog(vendor_id=vendor_id),
            }
        ), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Failed to delete override: {exc}"}), 500
