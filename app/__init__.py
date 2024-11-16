import logging
from flask import Flask
from controllers.booking_controller import booking_blueprint
from controllers.slot_controller import slot_blueprint
from controllers.game_controller import game_blueprint

from db.extensions import db
from .config import Config
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    app.register_blueprint(booking_blueprint, url_prefix='/api')  # Prefixing all routes with /api
    app.register_blueprint(slot_blueprint, url_prefix='/api')  # Prefixing all routes with /api
    app.register_blueprint(game_blueprint, url_prefix='/api')  # Prefixing all routes with /api

    # Configure logging
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    return app

