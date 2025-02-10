from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()

def configure_socketio(app):
    """
    Configures SocketIO with the Flask app.
    """
    socketio.init_app(app)
