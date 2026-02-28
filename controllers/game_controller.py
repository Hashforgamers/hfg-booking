from flask import Blueprint, jsonify, request
from services.booking_service import BookingService
from models.availableGame import AvailableGame
from models.openingDays import OpeningDay
from datetime import datetime
from flask_cors import cross_origin
import time
from threading import Lock


game_blueprint = Blueprint('game', __name__)
_GAMES_BY_VENDOR_CACHE = {}
_GAMES_BY_VENDOR_TTL_SECONDS = 30
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
    now = time.time()
    cache_key = f"{vendor_id}:{datetime.now().date().isoformat()}"
    cached_payload = _games_cache_get(cache_key, now)
    if cached_payload is not None:
        return jsonify(cached_payload), 200

    today = datetime.now().strftime('%a').lower()
    day_aliases = {today}
    if today == "tue":
        day_aliases.add("tues")
    if today == "thu":
        day_aliases.add("thurs")

    opening_days = (
        OpeningDay.query
        .with_entities(OpeningDay.day)
        .filter_by(vendor_id=vendor_id, is_open=True)
        .all()
    )
    open_days = {row.day.lower() for row in opening_days}

    if open_days and not (day_aliases & open_days):
        payload = {
            "message": "Shop is closed today, no games available.",
            "shop_open": False,
            "game_count": 0
        }
        _games_cache_set(cache_key, payload, now)
        return jsonify(payload), 200

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

    if not games:
        payload = {
            "message": "No games found for this vendor",
            "shop_open": True,
            "game_count": 0
        }
        _games_cache_set(cache_key, payload, now)
        return jsonify(payload), 200

    open_days_list = [row.day for row in opening_days]
    payload = {
        "games": [{
            "id": game.id,
            "game_name": game.game_name,
            "total_slots": game.total_slot,
            "single_slot_price": game.single_slot_price,
            "opening_days": open_days_list
        } for game in games],
        "shop_open": True,
        "game_count": len(games)
    }
    _games_cache_set(cache_key, payload, now)
    return jsonify(payload), 200

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
@cross_origin(origins=["http://localhost:3000", "https://dev-dashboard.hashforgamers.co.in", "https://dashboard.hashforgamers.co.in"])
def get_all_console_by_vendor_id(vendor_id):

    # Query games by vendor_id
    games = AvailableGame.query.filter_by(vendor_id=vendor_id).all()

    # If no games found, return an appropriate message
    if not games:
        return jsonify({
            "message": "No games found for this vendor",
            "shop_open": True,
            "game_count": 0
        }), 200

    # Return the game details along with the vendor's open days in JSON format
    return jsonify({
        "games": [{
            "id": game.id,
            "console_name": game.game_name,
            "console_price":game.single_slot_price
        } for game in games],
    })
