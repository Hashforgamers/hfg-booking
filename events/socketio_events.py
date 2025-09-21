# socketio_events.py

from flask import current_app
from flask_socketio import SocketIO, join_room, emit
from datetime import datetime

socketio: SocketIO | None = None  # Global socket instance

def register_socketio_events(socket: SocketIO):
    """
    Register WebSocket events with the given SocketIO instance.
    Provides vendor-specific rooms for booking updates and health checks.
    """
    global socketio
    socketio = socket

    @socketio.on("connect")
    def handle_connect():
        current_app.logger.info("Client connected to WebSocket")
        # Optionally, auto-join a general health room for all clients
        join_room("health")  # harmless if dashboard expects to listen here
        # Immediately acknowledge connection so clients can measure RTT
        emit("server_hello", {"ts": datetime.utcnow().isoformat() + "Z"})

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
            emit("vendor_connected", {"vendor_id": vendor_id}, room=f"vendor_{vendor_id}")
        else:
            current_app.logger.warning("connect_vendor called without vendor_id")

    @socketio.on("connect_admin")
    def handle_admin_connect(data):
        """
        Admin joins the admin dashboard room.
        Example client emit:
            socket.emit("connect_admin", {});
        """
        join_room("dashboard_admin")
        current_app.logger.info("Admin joined dashboard_admin")
        emit("admin_connected", {"ts": datetime.utcnow().isoformat() + "Z"}, room="dashboard_admin")

    # Health-check: request/response ping
    @socketio.on("ping_health")
    def handle_ping_health(payload=None):
        """
        Dashboard/service can emit:
            socket.emit("ping_health", { service: 'dashboard', nonce: 'abc123' })
        Server replies only to sender:
            pong_health with same nonce and server timestamp.
        """
        data = payload or {}
        resp = {
            "status": "ok",
            "nonce": data.get("nonce"),
            "server_ts": datetime.utcnow().isoformat() + "Z",
        }
        emit("pong_health", resp)  # reply to the caller only

    # Optional: server-driven heartbeat to a known room
    # Call this from a background task/timer in app startup to emit periodically.
    def emit_heartbeat():
        """
        Emits a heartbeat to the 'health' room that any listener can subscribe to.
        Intended to be called by a periodic scheduler.
        """
        if socketio is None:
            return
        payload = {
            "status": "alive",
            "server_ts": datetime.utcnow().isoformat() + "Z",
        }
        socketio.emit("server_heartbeat", payload, room="health")

    # Expose helper on the socketio instance for scheduling from app factory
    socketio.emit_heartbeat = emit_heartbeat  # type: ignore[attr-defined]
