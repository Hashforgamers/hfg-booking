from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from db.extensions import db, migrate, mail
from controllers.booking_controller import booking_blueprint
from controllers.slot_controller import slot_blueprint
from controllers.game_controller import game_blueprint
from controllers.pass_controller import pass_blueprint
from .config import Config
from events.socketio_events import register_socketio_events
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

import logging
import os

# Initialize socketio once
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins=[
        "http://localhost:3000",
        "https://dev-dashboard.hashforgamers.co.in",
        "https://dashboard.hashforgamers.co.in",
        "https://amritb.github.io",   # ✅ added here
        "https://hfg-booking-hmnx.onrender.com",
        "https://hfg-booking.onrender.com"
    ],
    logger=True,
    engineio_logger=True
)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    CORS(
        app,
        origins=[
            "http://localhost:3000",
            "https://dev-dashboard.hashforgamers.co.in",
            "https://dashboard.hashforgamers.co.in",
        ],
        resources={r"/api/*": {"origins": "*"}},
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )

    # Blueprints
    app.register_blueprint(booking_blueprint, url_prefix="/api")
    app.register_blueprint(slot_blueprint, url_prefix="/api")
    app.register_blueprint(game_blueprint, url_prefix="/api")
    app.register_blueprint(pass_blueprint, url_prefix='/api')

    # Logging
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Redis + RQ
    redis_conn = Redis.from_url(app.config["REDIS_URL"])
    queue = Queue("booking_tasks", connection=redis_conn)
    scheduler = Scheduler(queue=queue, connection=redis_conn)
    app.extensions["scheduler"] = scheduler

    # SocketIO with Redis message queue
    socketio.init_app(app, message_queue=app.config["REDIS_URL"])
    register_socketio_events(socketio)

    return app  # ✅ only return Flask app

# Expose app for Gunicorn
app = create_app()
