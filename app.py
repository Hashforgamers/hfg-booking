from app import create_app

app, socketio = create_app()  # expose both to Gunicorn
