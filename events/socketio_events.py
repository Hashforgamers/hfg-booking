# socketio_events.py

from flask_socketio import SocketIO
import json

global socketio  

def register_socketio_events(socket: SocketIO):
    """
    Register WebSocket events with the given SocketIO instance.
    This will allow all controllers to access these events.
    """
    # Declare the socketio as a global variable
    socketio = socket  # Set the global socketio variable

    @socketio.on('connect')
    def handle_connect():
        print("Client connected")
        socketio.emit('message', {"data": "Connected to WebSocket server"})

    @socketio.on('slot_booked')
    def handle_slot_booked(data):
        try:
            # Parse the JSON string into a dictionary
            data = json.loads(data)
            print(f"Slot {data['slot_id']} has been booked. Status: {data['status']}")
            socketio.emit('slot_booked', {'slot_id': data['slot_id'], 'status': 'booked'})
        except json.JSONDecodeError:
            print(f"Failed to decode JSON: {data}")
            
    @socketio.on('booking_updated')
    def handle_booking_updated(data):
        print(f"Booking {data['booking_id']} updated. Status: {data['status']}")
        socketio.emit('booking_updated', data)