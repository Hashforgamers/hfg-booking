from flask import Blueprint, request, jsonify
from services.slot_service import SlotService
from models.slot import Slot
from models.availableGame import AvailableGame
from models.openingDays import OpeningDay
from datetime import datetime


slot_blueprint = Blueprint('slots', __name__)

@slot_blueprint.route('/slots', methods=['GET'])
def get_slots():
    slots = SlotService.get_all_slots()

    # Convert each slot to a dictionary using to_dict()
    slots_dict = [slot.to_dict() for slot in slots]
    
    return jsonify(slots_dict)

@slot_blueprint.route('/slots/game/<int:game_id>', methods=['GET'])
def get_slots_by_game_id(game_id):
    # Get the game based on the game_id
    game = AvailableGame.query.get(game_id)
    
    # If the game is not found, return an appropriate message
    if not game:
        return jsonify({"message": "Game not found"}), 404

    # Get the vendor_id from the game
    vendor_id = game.vendor_id
    
    # Get today's day of the week (e.g., 'mon', 'tues', 'wed')
    today = datetime.now().strftime('%a').lower()  # e.g., 'mon', 'tues', 'wed'

    # Query opening days for the vendor (filter by vendor_id and is_open=True)
    opening_days = OpeningDay.query.filter_by(vendor_id=vendor_id, is_open=True).all()

    # Extract the days the vendor is open
    open_days = [opening_day.day.lower() for opening_day in opening_days]

    # If the shop is not open today, return a message
    if today not in open_days:
        return jsonify({
            "message": "Shop is closed today, no slots available.",
            "shop_open": False,
            "slot_count": 0
        }), 200

    # Get all the slots for the given game (filtered by game_id)
    slots = Slot.query.filter_by(gaming_type_id=game_id).all()

    # If no slots found, return an appropriate message
    if not slots:
        return jsonify({
            "message": "No slots found for this game",
            "shop_open": True,
            "slot_count": 0
        }), 200

    # Convert each slot to a dictionary using to_dict()
    slots_dict = [slot.to_dict() for slot in slots]

    return jsonify({
        "slots": slots_dict,
        "shop_open": True,
        "slot_count": len(slots)
    })