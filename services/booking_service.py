from models.booking import Booking, db
from models.availableGame import AvailableGame
from flask_socketio import socketio
from models.slot import Slot
from models.booking import Booking
from flask import current_app
from db.extensions import db
from datetime import datetime
from sqlalchemy.sql import text
from flask import current_app


class BookingService:
    socketio = None  # Placeholder for the socketio instance

    @staticmethod
    def set_socketio(socketio_instance):
        BookingService.socketio = socketio_instance  # Set the socketio instance

    @staticmethod
    def get_user_bookings(user_id):
        return Booking.query.filter_by(user_id=user_id).all()

    @staticmethod
    def get_user_bookings(user_id):
        return Booking.query.filter_by(user_id=user_id).all()

    @staticmethod
    def cancel_booking(booking_id):
        booking = Booking.query.get(booking_id)
        if not booking:
            raise ValueError("Booking does not exist.")
        
        # Free up the slot for the game
        game = AvailableGame.query.get(booking.game_id)
        game.total_slot += 1
        db.session.add(game)

        db.session.delete(booking)
        db.session.commit()
        
        # Emit real-time cancellation event
        socketio.emit('booking_updated', {'booking_id': booking_id, 'status': 'canceled'})
        return {"message": "Booking canceled successfully."}

    @staticmethod
    def verifyPayment(payment_id):
        return payment_id == "1234"

    @staticmethod
    def create_booking(slot_id, game_id, user_id, socketio, book_date):
        # ✅ Get vendor_id from available_games
        available_game = db.session.execute(
            text("SELECT vendor_id FROM available_games WHERE id = (SELECT gaming_type_id FROM slots WHERE id = :slot_id)"),
            {"slot_id": slot_id}
        ).fetchone()

        if not available_game:
            raise ValueError("Vendor not found for this slot.")

        vendor_id = available_game[0]

        current_app.logger.info(f"Test1 {vendor_id} . {slot_id}, {book_date}")

        # ✅ Check availability in the VENDOR_{vendor_id}_SLOT table
        slot_entry = db.session.execute(
            text(f"""
                SELECT * FROM VENDOR_{vendor_id}_SLOT
                WHERE slot_id = :slot_id AND date = :book_date
            """),
            {"slot_id": slot_id, "book_date": book_date}
        ).fetchone()

        current_app.logger.info(f"Test {slot_entry} .")

        if not slot_entry or slot_entry[0] <= 0:
            raise ValueError("Slot is fully booked for this date.")

        try:
            # ✅ Decrease `available_slot` by 1 in the table
            update_query = text(f"""
                UPDATE VENDOR_{vendor_id}_SLOT
                SET available_slot = available_slot - 1,
                    is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                WHERE slot_id = :slot_id
                AND date = :book_date;
            """)
            db.session.execute(update_query, {"slot_id": slot_id, "book_date": book_date})
            db.session.commit()

            # ✅ Create booking
            booking = Booking(slot_id=slot_id, game_id=game_id, user_id=user_id, status='pending_verified')
            db.session.add(booking)
            db.session.commit()

            socketio.emit('slot_pending', {'slot_id': slot_id, 'booking': booking.id, 'status': 'pending'})

            # ✅ Emit WebSocket event
            if BookingService.socketio:
                BookingService.socketio.emit('booking_updated', {
                    'booking_id': booking.id, 'status': 'pending_verified'
                }, room=None)  # 'room=None' sends to all

            return booking

        except Exception as e:
            db.session.rollback()
            raise ValueError(f"Failed to create booking: {str(e)}")

    @staticmethod
    def release_slot(slot_id, booking_id, book_date):
        """Function to release the slot after 10 seconds if not verified"""
        from app import create_app

        # Create the Flask app
        app, _ = create_app()
        
        # Push the application context inside the job
        with app.app_context():
            try:
                booking = Booking.query.get(booking_id)

                if booking and booking.status == "pending_verified":
                    # ✅ Get vendor_id from available_games
                    available_game = db.session.execute(
                        text("SELECT vendor_id FROM available_games WHERE id = (SELECT gaming_type_id FROM slots WHERE id = :slot_id)"),
                        {"slot_id": slot_id}
                    ).fetchone()

                    if not available_game:
                        current_app.logger.error("Vendor not found for this slot.")
                        return

                    vendor_id = available_game[0]

                    # ✅ Restore `available_slot` in the table
                    update_query = text(f"""
                        UPDATE VENDOR_{vendor_id}_SLOT
                        SET available_slot = available_slot + 1,
                            is_available = TRUE
                        WHERE slot_id = :slot_id
                        AND date = :book_date;
                    """)
                    db.session.execute(update_query, {"slot_id": slot_id, "book_date": book_date})
                    db.session.commit()

                    # ✅ Update booking status
                    booking.status = 'verification_failed'
                    db.session.commit()

                    # ✅ Emit WebSocket event to update slot status
                    socketio = current_app.extensions['socketio']
                    socketio.emit('slot_released', {
                        'slot_id': slot_id,
                        'slot_status': 'available',
                        'booking_id': booking_id,
                        'booking_status': 'verification_failed'
                    })

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Failed to release slot: {str(e)}")
            finally:
                db.session.remove()  # Ensure DB session cleanup

