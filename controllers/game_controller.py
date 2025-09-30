from flask import Blueprint, jsonify, request
from services.booking_service import BookingService
from models.availableGame import AvailableGame
from models.openingDays import OpeningDay
from datetime import datetime
from flask_cors import cross_origin

game_blueprint = Blueprint('game', __name__)

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
    # Get today's day of the week (e.g., 'mon', 'tues', 'wed', etc.)
    today = datetime.now().strftime('%a').lower()  # e.g., 'mon', 'tues', 'wed'

    # Query opening days for the vendor (filter by vendor_id and is_open=True)
    opening_days = OpeningDay.query.filter_by(vendor_id=vendor_id, is_open=True).all()

    # Extract the days the vendor is open
    open_days = [opening_day.day.lower() for opening_day in opening_days]

    # If the shop is not open today, return a message
    if today not in open_days:
        return jsonify({
            "message": "Shop is closed today, no games available.",
            "shop_open": False,
            "game_count": 0
        }), 200

    # Query games by vendor_id
    games = AvailableGame.query.filter_by(vendor_id=vendor_id).all()

    # If no games found, return an appropriate message
    if not games:
        return jsonify({
            "message": "No games found for this vendor",
            "shop_open": True,
            "game_count": 0
        }), 200

    # Convert opening days to a list of day strings (e.g., 'mon', 'tues', etc.)
    open_days_list = [opening_day.day for opening_day in opening_days]

    # Return the game details along with the vendor's open days in JSON format
    return jsonify({
        "games": [{
            "id": game.id,
            "game_name": game.game_name,
            "total_slots": game.total_slot,
            "single_slot_price": game.single_slot_price,
            "opening_days": open_days_list  # Include the list of open days for the vendor
        } for game in games],
        "shop_open": True,
        "game_count": len(games)
    })

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
