from gevent import monkey
monkey.patch_all()

from flask import Flask
from flask import current_app
from flask_socketio import SocketIO
from flask_cors import CORS
import logging
import os
# import redis
from redis import Redis
from rq import Queue  # Import RQ Queue
from rq_scheduler import Scheduler  # Import RQ Scheduler
from datetime import datetime, timedelta

from db.extensions import db, migrate
from controllers.booking_controller import booking_blueprint
from controllers.slot_controller import slot_blueprint
from controllers.game_controller import game_blueprint
from .config import Config
from events.socketio_events import register_socketio_events  # Import the socket event registration function
from rq.registry import FinishedJobRegistry

def create_app():
    app = Flask(__name__)
    # Initialize SocketIO globally
    socketio = SocketIO(app, cors_allowed_origins="*", transports=['websocket', 'polling'], async_mode="gevent", logger=True, engineio_logger=True)

    app.config.from_object(Config)
    app.config['REDIS_URL'] = "redis://red-culflulds78s73bqveqg:6379"

    # Initialize CORS
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Initialize SocketIO with the app
    socketio.init_app(app, message_queue=app.config['REDIS_URL'])

    # Register WebSocket events with the socketio instance
    register_socketio_events(socketio)  # Pass socketio here to register events

    # Register blueprints
    app.register_blueprint(booking_blueprint, url_prefix='/api')
    app.register_blueprint(slot_blueprint, url_prefix='/api')
    app.register_blueprint(game_blueprint, url_prefix='/api')

    # Configure logging
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Initialize Redis connection
    redis_conn = Redis.from_url(app.config['REDIS_URL'])
    app.logger.info(f"Ping Redis: {redis_conn.ping()}") 

    # Create RQ Queue & Scheduler
    queue = Queue('booking_tasks', connection=redis_conn)
    scheduler = Scheduler(queue=queue, connection=redis_conn)

    # Add scheduler to app.extensions
    app.extensions['scheduler'] = scheduler
    
    return app, socketio  # Return both app and socketio as a tuple