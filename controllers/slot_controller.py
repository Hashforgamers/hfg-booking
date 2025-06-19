from flask import Blueprint, jsonify, current_app, request
from models.slot import Slot
from flask_socketio import emit
from db.extensions import db
from sqlalchemy.sql import text 
from datetime import datetime

slot_blueprint = Blueprint('slots', __name__)

@slot_blueprint.route('/slots', methods=['GET'])
def get_slots():
    try:
        slots = Slot.query.all()
        current_app.logger.info(f"Fetched {len(slots)} slots")
        return jsonify([slot.to_dict() for slot in slots]), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching slots: {str(e)}")
        return jsonify({"error": str(e)}), 400

@slot_blueprint.route('/getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>', methods=['GET'])
def get_slots_on_game_id(vendorId, gameId, date):
    """
    Fetch available slots from the dynamic VENDOR_<vendorId>_SLOT table based on date and gameId.
    Append single_slot_price from available_games.
    """
    try:
        if len(date) != 8 or not date.isdigit():
            return jsonify({"error": "Invalid date format. Use YYYYMMDD."}), 400

        formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        table_name = f"VENDOR_{vendorId}_SLOT"

        # Step 1: Get price from AvailableGame
        available_game = AvailableGame.query.filter_by(id=gameId, vendor_id=vendorId).first()
        if not available_game:
            return jsonify({"error": "Game not found for this vendor."}), 404

        single_slot_price = available_game.single_slot_price

        # Step 2: Fetch relevant slots from dynamic slot table
        sql_query = text(f"""
            SELECT slot_id, is_available, available_slot
            FROM {table_name}
            WHERE date = :date AND slot_id IN (
                SELECT id FROM slots WHERE gaming_type_id = :gameId
            )
            ORDER BY slot_id;
        """)
        result = db.session.execute(sql_query, {"date": formatted_date, "gameId": gameId}).fetchall()

        slots = []
        for row in result:
            slot = Slot.query.get(row[0])
            if slot:
                slots.append({
                    "slot_id": row[0],
                    "start_time": slot.start_time.strftime("%H:%M:%S"),
                    "end_time": slot.end_time.strftime("%H:%M:%S"),
                    "is_available": row[1],
                    "available_slot": row[2],
                    "single_slot_price": single_slot_price  # 🔥 Added here
                })

        return jsonify({"slots": slots}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@slot_blueprint.route('/getSlotList/vendor/<int:vendor_id>/game/<int:game_id>', methods=['GET'])
def get_next_six_slot_for_game(vendor_id, game_id):
    """
    Fetches the next six available slots for a given vendor and game based on the current time.
    """
    try:
        current_app.logger.info("Fetching available slots for vendor_id=%s, game_id=%s", vendor_id, game_id)

        # Get current time and today's date
        current_time = datetime.now().time()
        today_date = datetime.now().date()

        current_app.logger.info(f"current Time={current_time}, Date={today_date}")

        # Fetch the next 6 slots from the Slot table based on the game_id and current time
        next_slots = db.session.query(Slot.id, Slot.start_time, Slot.end_time).filter(
            Slot.gaming_type_id == game_id,
            Slot.start_time > current_time  # Get only future slots
        ).order_by(Slot.start_time).limit(6).all()

        if not next_slots:
            return jsonify({"message": "No available slots found"}), 404

        slot_ids = [slot.id for slot in next_slots]

        # Fetch slot availability from the dynamic VENDOR_{vendor_id}_SLOT table
        slot_query = text(f"""
            SELECT slot_id, is_available
            FROM VENDOR_{vendor_id}_SLOT
            WHERE date = :today_date
            AND slot_id IN :slot_ids
            ORDER BY slot_id;
        """)

        slot_results = db.session.execute(slot_query, {"today_date": today_date, "slot_ids": tuple(slot_ids)}).fetchall()

        # Map slot availability
        availability_map = {row.slot_id: row.is_available for row in slot_results}

        # Construct response
        slots = []
        for slot in next_slots:
            slots.append({
                "slot_id": slot.id,
                "start_time": slot.start_time.strftime("%H:%M:%S"),
                "end_time": slot.end_time.strftime("%H:%M:%S"),
                "is_available": availability_map.get(slot.id, False)  # Default to False if not found
            })

        return jsonify(slots), 200

    except Exception as e:
        current_app.logger.error(f"Failed to fetch slots: {str(e)}")
        return jsonify({"message": "Failed to fetch slots", "error": str(e)}), 500

def register_socketio_events(socketio):
    """
    Register WebSocket events with the given SocketIO instance.
    """
    @socketio.on('connect')
    def handle_connect():
        current_app.logger.info("Client connected")
        emit('message', {"data": "Connected to WebSocket server"})

    @socketio.on('get_slots')
    def handle_get_slots(data):
        try:
            # Query the database for slot details
            slots = Slot.query.all()
            slots_data = [slot.to_dict() for slot in slots]
            emit('slot_details', {"slots": slots_data}, broadcast=False)
        except Exception as e:
            current_app.logger.error(f"Error fetching slots: {str(e)}")
            emit('error', {"message": f"Error fetching slots: {str(e)}"})
