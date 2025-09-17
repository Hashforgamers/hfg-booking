# socketio_events.py

from flask import current_app
from flask_socketio import SocketIO, join_room

socketio: SocketIO | None = None  # Global socket instance


def register_socketio_events(socket: SocketIO):
    """
    Register WebSocket events with the given SocketIO instance.
    Provides vendor-specific rooms for booking updates.
    """
    global socketio
    socketio = socket

    @socketio.on("connect")
    def handle_connect():
        current_app.logger.info("Client connected to WebSocket")

    @socketio.on("disconnect")
    def handle_disconnect():
        current_app.logger.info("Client disconnected from WebSocket")

    @socketio.on("connect_vendor")
    def handle_vendor_connect(data):
        """
        Vendor joins their own room based on vendor_id.
        Example client emit:
            socket.emit("connect_vendor", { vendor_id: 123 });
        """
        vendor_id = data.get("vendor_id")
        if vendor_id:
            join_room(f"vendor_{vendor_id}")
            current_app.logger.info(f"Vendor {vendor_id} joined their room")
        else:
            current_app.logger.warning("connect_vendor called without vendor_id")

    @socketio.on("connect_admin")
    def handle_vendor_connect(data):
        """
        Vendor joins their own room based on vendor_id.
        Example client emit:
            socket.emit("connect_vendor", { vendor_id: 123 });
        """
        join_room(f"dashboard_admin")
        current_app.logger.warning("connect_admin called")
