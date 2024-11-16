from flask import Blueprint, request, jsonify
from services.booking_service import BookingService
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from db.extensions import db
from models.slot import Slot
from models.availableGame import AvailableGame
from models.openingDays import OpeningDay
from models.booking import Booking


booking_blueprint = Blueprint('bookings', __name__)


@booking_blueprint.route('/bookings', methods=['POST'])
def create_booking():
    data = request.json

    # Extract slot_id, user_id, and game_id from request
    slot_id = data.get("slot_id")
    user_id = data.get("user_id")
    game_id = data.get("game_id")

    if not slot_id or not user_id or not game_id:
        return jsonify({"message": "slot_id, game_id, and user_id are required"}), 400

    # Fetch the slot and game details
    slot = Slot.query.get(slot_id)
    game = AvailableGame.query.get(game_id)

    if not slot or not game:
        return jsonify({"message": "Slot or Game not found"}), 404

    # Verify the slot belongs to the game
    if slot.gaming_type_id != game_id:
        return jsonify({"message": "Slot does not belong to the specified game"}), 400

    # Get vendor ID from game
    vendor_id = game.vendor_id

    # Check if the shop is open today
    today = datetime.now().strftime('%a').lower()
    opening_days = OpeningDay.query.filter_by(vendor_id=vendor_id, is_open=True).all()
    open_days = [opening_day.day.lower() for opening_day in opening_days]

    if today not in open_days:
        return jsonify({"message": "Shop is closed today, cannot book the slot"}), 400

    # Check if the slot is available
    if not slot.is_available or slot.available_slot <= 0:
        return jsonify({"message": "Slot is fully booked"}), 400

    # Create a new booking
    try:
        booking = Booking(
            slot_id=slot_id,
            game_id=game_id,
            user_id=user_id,
            status='pending_verified'
        )
        db.session.add(booking)
        db.session.commit()
        return jsonify({
            "message": "Booking created successfully",
            "booking_id": booking.id,
            "status": booking.status
        }), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Failed to create booking, please try again"}), 500

@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    data = request.json

    # Extract booking_id and payment_status from request
    booking_id = data.get("booking_id")
    payment_id = data.get("payment_id")

    if not booking_id or not payment_id:
        return jsonify({"message": "booking_id and payment_id are required"}), 400

    # Fetch the booking
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({"message": "Booking not found"}), 404

    if booking.status == 'confirmed':
        return jsonify({"message": "Booking is already confirmed"}), 400

    if BookingService.verifyPayment(payment_id):
        return jsonify({"message": "Payment not verified, cannot confirm booking"}), 400

    # Confirm the booking and decrement slot count
    slot = Slot.query.get(booking.slot_id)
    try:
        with db.session.begin_nested():
            booking.status = 'confirmed'
            slot.available_slot -= 1
            if slot.available_slot <= 0:
                slot.is_available = False
            db.session.commit()

        return jsonify({"message": "Booking confirmed successfully", "booking_id": booking.id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to confirm booking", "error": str(e)}), 500

@booking_blueprint.route('/users/<int:user_id>/bookings', methods=['GET'])
def get_user_bookings(user_id):
    bookings = BookingService.get_user_bookings(user_id)
    return jsonify([booking.to_dict() for booking in bookings])

@booking_blueprint.route('/bookings/<int:booking_id>', methods=['DELETE'])
def cancel_booking(booking_id):
    success = BookingService.cancel_booking(booking_id)
    if not success:
        return jsonify({"message": "Booking not found"}), 404
    return jsonify({"message": "Booking cancelled"})
