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
from models.transaction import Transaction
from models.user import User


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

    @staticmethod
    def insert_into_vendor_dashboard_table(trans_id, console_id):
        """Inserts booking and transaction details into the vendor dashboard table."""
        
        # Fetch required objects
        trans_obj = Transaction.query.filter_by(id=trans_id).first()
        if not trans_obj:
            raise ValueError(f"Transaction with ID {trans_id} not found.")

        user_obj = User.query.filter_by(id=trans_obj.user_id).first()
        book_obj = Booking.query.filter_by(id=trans_obj.booking_id).first()
        slot_obj = Slot.query.filter_by(id=book_obj.slot_id).first()
        available_game_obj = AvailableGame.query.filter_by(id=book_obj.game_id).first()
        if book_obj.status == "extra":
            book_status = "extra"
        else
            book_status = "upcoming"

        vendor_id = trans_obj.vendor_id
        table_name = f"VENDOR_{vendor_id}_DASHBOARD"

        # SQL Query for insertion
        sql_insert = text(f"""
            INSERT INTO {table_name} 
            (username, user_id, start_time, end_time, date, book_id, game_id, game_name, console_id, book_status)
            VALUES (:username, :user_id, :start_time, :end_time, :date, :book_id, :game_id, :game_name, :console_id, :book_status)
        """)

        # Execute query with parameter binding
        db.session.execute(sql_insert, {
            "username": user_obj.name,
            "user_id": user_obj.id,
            "start_time": slot_obj.start_time,
            "end_time": slot_obj.end_time,
            "date": trans_obj.booked_date,
            "book_id": trans_obj.booking_id,
            "game_id": book_obj.game_id,
            "game_name": available_game_obj.game_name,
            "console_id": console_id,
            "book_status":book_status
        })

        db.session.commit()
        current_app.logger.info(f"Inserted transaction {trans_id} into {table_name}")

    @staticmethod
    def insert_into_vendor_promo_table(trans_id, console_id):
        """Inserts promo details into the vendor-specific promo table."""

        # Fetch transaction, booking
        trans_obj = Transaction.query.filter_by(id=trans_id).first()
        if not trans_obj:
            raise ValueError(f"Transaction with ID {trans_id} not found.")

        booking_obj = Booking.query.filter_by(id=trans_obj.booking_id).first()
        if not booking_obj:
            raise ValueError(f"Booking with ID {trans_obj.booking_id} not found.")

        # Fetch promo data — assume it's in the transaction metadata or external source
        promo_code = "LAUNCH10"
        discount_applied = "10"
        actual_price = trans_obj.amount if trans_obj.amount else 0.0

        if not promo_code or discount_applied is None:
            current_app.logger.warning(f"No promo data found for transaction {trans_id}. Skipping promo insertion.")
            return

        # Compose table name
        vendor_id = trans_obj.vendor_id
        table_name = f"VENDOR_{vendor_id}_PROMO_DETAIL"

        # SQL insert
        sql_insert = text(f"""
            INSERT INTO {table_name} 
            (booking_id, transaction_id, promo_code, discount_applied, actual_price)
            VALUES 
            (:booking_id, :transaction_id, :promo_code, :discount_applied, :actual_price)
        """)

        db.session.execute(sql_insert, {
            "booking_id": trans_obj.booking_id,
            "transaction_id": trans_obj.id,
            "promo_code": promo_code,
            "discount_applied": discount_applied,
            "actual_price": actual_price
        })

        db.session.commit()
        current_app.logger.info(f"Inserted promo detail for transaction {trans_id} into {table_name}")

    @staticmethod
    def update_dashboard_booking_status(trans_id, vendor_id, new_status):
        """Updates the booking status in the vendor dashboard table for a given transaction."""
        table_name = f"VENDOR_{vendor_id}_DASHBOARD"

        sql_update = text(f"""
            UPDATE {table_name}
            SET book_status = :new_status
            WHERE book_id = (
                SELECT booking_id FROM transactions WHERE id = :trans_id
            )
        """)

        db.session.execute(sql_update, {
            "trans_id": trans_id,
            "new_status": new_status
        })
        db.session.commit()
        current_app.logger.info(f"Updated booking status to '{new_status}' for transaction {trans_id} in {table_name}")
