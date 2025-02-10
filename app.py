from app import create_app

# Create the Flask app
app, socketio = create_app()

if __name__ == '__main__':
    # Directly use socketio.run with the app instance
        
    socketio.run(app, host='0.0.0.0', port=5054, debug=True)
