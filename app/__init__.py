from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from db.extensions import db, migrate, mail
from controllers.booking_controller import booking_blueprint
from controllers.slot_controller import slot_blueprint
from controllers.game_controller import game_blueprint
from .config import Config
from events.socketio_events import register_socketio_events
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

import logging
import os

# Initialize socketio with Eventlet
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*", logger=True, engineio_logger=True)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    CORS(app)

    # Blueprints
    app.register_blueprint(booking_blueprint, url_prefix="/api")
    app.register_blueprint(slot_blueprint, url_prefix="/api")
    app.register_blueprint(game_blueprint, url_prefix="/api")

    # Configure logging
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


    # Redis + RQ
    redis_conn = Redis.from_url(app.config.get("REDIS_URL"))
    queue = Queue("booking_tasks", connection=redis_conn)
    scheduler = Scheduler(queue=queue, connection=redis_conn)
    app.extensions["scheduler"] = scheduler

    # SocketIO
    socketio.init_app(app, message_queue=app.config.get("REDIS_URL"))
    register_socketio_events(socketio)

    return app, socketio
