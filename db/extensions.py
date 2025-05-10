from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_mail import Mail

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
mail = Mail()

def configure_socketio(app):
    """
    Configures SocketIO with the Flask app.
    """
    socketio.init_app(app)
