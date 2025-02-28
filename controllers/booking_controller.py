from flask import Blueprint, request, jsonify, current_app
from services.booking_service import BookingService
from db.extensions import db
from models.slot import Slot
from models.booking import Booking
from models.booking import Booking
import logging
from datetime import datetime, timedelta
from rq import Queue
from rq_scheduler import Scheduler
from models.transaction import Transaction
from models.availableGame import AvailableGame, available_game_console
from models.vendor import Vendor
from models.user import User
from models.contactInfo import ContactInfo
from models.console import Console
from models.contactInfo import ContactInfo

from sqlalchemy.sql import text
from sqlalchemy.orm import joinedload

from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError


booking_blueprint = Blueprint('bookings', __name__)

@booking_blueprint.route('/bookings', methods=['POST'])
def create_booking():
    current_app.logger.info(f"Current App in Blueprint {current_app}")
    data = request.json
    slot_id = data.get("slot_id")
    user_id = data.get("user_id")
    game_id = data.get("game_id")
    book_date = data.get("book_date")  # ✅ Get `book_date` from request

    if not slot_id or not user_id or not game_id or not book_date:
        return jsonify({"message": "slot_id, game_id, user_id, and book_date are required"}), 400

    try:
        socketio = current_app.extensions['socketio']

        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()

        # ✅ Check if there is at least one available slot before booking
        slot_entry = db.session.execute(text(f"""
            SELECT available_slot, is_available
            FROM VENDOR_{available_game.vendor_id}_SLOT
            WHERE slot_id = :slot_id AND date = :book_date
        """), {"slot_id": slot_id, "book_date": book_date}).fetchone()

        if slot_entry is None or slot_entry[0] <= 0 or not slot_entry[1]:
            return jsonify({"message": "Slot is not available for booking"}), 400
        
        # ✅ Create the booking
        booking = BookingService.create_booking(slot_id, game_id, user_id, socketio, book_date)
        db.session.commit()

        # Schedule auto-release after 10 seconds
        scheduler = current_app.extensions['scheduler']
        scheduler.enqueue_in(
            timedelta(seconds=10),
            BookingService.release_slot,
            slot_id,
            booking.id,
            book_date  # ✅ Pass `book_date`
        )

        return jsonify({"message": "Slot frozen for 10 seconds", "slot_id": slot_id}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to freeze slot", "error": str(e)}), 500

@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    data = request.json
    booking_id = data.get("booking_id")
    payment_id = data.get("payment_id")

    if not booking_id or not payment_id:
        return jsonify({"message": "booking_id and payment_id are required"}), 400

    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({"message": "Booking not found"}), 404

    if booking.status == 'confirmed':
        return jsonify({"message": "Booking is already confirmed"}), 400

    if booking.status == 'verification_failed':
        return jsonify({"message": "Booking is already failed"}), 400

    socketio = current_app.extensions['socketio']

    try:
        with db.session.begin_nested():  # Start a SAVEPOINT transaction
            if not BookingService.verifyPayment(payment_id):
                raise ValueError("Payment not verified")

            # Confirm booking
            booking.status = 'confirmed'

            # 🚀 FIX: Correctly query the slot using slot_id
            slot = db.session.query(Slot).filter(Slot.id == booking.slot_id).first()
            if not slot:
                raise Exception(f"Slot not found for slot_id: {slot_id}")

            # Fetch available game correctly
            available_game = db.session.query(AvailableGame).filter(AvailableGame.id == slot.gaming_type_id).first()
            if not available_game:
                raise Exception("AvailableGame not found")

            # Fetch vendor correctly
            vendor = db.session.query(Vendor).filter(Vendor.id == available_game.vendor_id).first()
            if not vendor:
                raise Exception("Vendor not found")

            user_id = booking.user_id

            user= db.session.query(User).filter(User.id == user_id).first()

            # Create a transaction
            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor.id,
                user_id=user.id,
                booked_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                amount=available_game.single_slot_price,
                mode_of_payment="online",
                booking_type="hash",
                settlement_status="pending"
            )

            db.session.add(transaction)
            db.session.commit()
        
        db.session.commit()  # Commit the transaction **after** exiting the block

        # ✅ Emit WebSocket event AFTER transaction commits
        socketio.emit('slot_booked', {'slot_id': booking.slot_id, 'booking_id': booking.id , 'status': 'booked'})

        return jsonify({"message": "Booking confirmed successfully", "booking_id": booking.id}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to confirm booking", "error": str(e)}), 500

@booking_blueprint.route('/users/<int:user_id>/bookings', methods=['GET'])
def get_user_bookings(user_id):
    bookings = BookingService.get_user_bookings(user_id)
    return jsonify([booking.to_dict() for booking in bookings])

@booking_blueprint.route('/bookings/<int:booking_id>', methods=['DELETE'])
def cancel_booking(booking_id):
    try:
        success = BookingService.cancel_booking(booking_id)
        socketio.emit('booking_updated', {'booking_id': booking_id, 'status': 'canceled'})
        return jsonify({"message": success["message"]})
    except ValueError:
        return jsonify({"message": "Booking not found"}), 404

@booking_blueprint.route('/bookings/direct', methods=['POST'])
def direct_booking():
    current_app.logger.info("Direct Booking Triggered")
    data = request.json

    user_id = data.get("user_id")
    game_id = data.get("game_id")
    booked_date = data.get("booked_date")
    selected_slots = data.get("selected_slots", [])
    console_type = data.get("console_type")
    system_number = data.get("system_number")
    payment_method = data.get("payment_method")
    payment_status = data.get("payment_status")
    total_amount = data.get("total_amount")
    additional_request = data.get("additional_request")
    user = db.session.query(User).filter(User.id == user_id).first()
    user_name = user.name

    if not user_id or not game_id or not booked_date or not selected_slots:
        return jsonify({"message": "user_id, game_id, booked_date, and selected_slots are required"}), 400

    try:
        socketio = current_app.extensions['socketio']
        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()

        if not available_game:
            return jsonify({"message": "Game not found"}), 404

        vendor_id = available_game.vendor_id

        # ✅ Fetch all required slots
        slot_entries = db.session.execute(
            text(f"""
                SELECT slot_id, available_slot, is_available
                FROM VENDOR_{vendor_id}_SLOT
                WHERE slot_id IN (SELECT id FROM slots WHERE start_time IN :selected_slots)
                AND date = :booked_date
            """),
            {"selected_slots": tuple(selected_slots), "booked_date": booked_date}
        ).fetchall()

        # ✅ Check if all slots are available
        if len(slot_entries) != len(selected_slots):
            return jsonify({"message": "One or more slots are invalid or unavailable"}), 400

        for slot in slot_entries:
            if slot[1] <= 0 or not slot[2]:
                return jsonify({"message": f"Slot {slot[0]} is fully booked"}), 400

        # ✅ Begin transaction to book all slots
        bookings = []
        for slot in slot_entries:
            slot_id = slot[0]

            booking = Booking(
                slot_id=slot_id,
                game_id=game_id,
                user_id=user_id,
                status="confirmed"
            )
            db.session.add(booking)
            bookings.append(booking)

            # ✅ Decrease `available_slot` count
            db.session.execute(
                text(f"""
                    UPDATE VENDOR_{vendor_id}_SLOT
                    SET available_slot = available_slot - 1,
                        is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                    WHERE slot_id = :slot_id
                    AND date = :booked_date;
                """),
                {"slot_id": slot_id, "booked_date": booked_date}
            )

        db.session.commit()  # ✅ Commit only after all bookings succeed

        # ✅ Store individual transaction details for each booking
        for booking in bookings:
            transaction = Transaction(
                booking_id=booking.id,  # Linking each booking
                vendor_id=vendor_id,
                user_id=user_id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_time=datetime.utcnow().time(),
                user_name=user_name,
                amount=available_game.single_slot_price,  # Assuming the amount is per slot
                mode_of_payment=payment_method,
                booking_type="direct",
                settlement_status="pending" if payment_status != "paid" else "completed"
            )
            db.session.add(transaction)

        db.session.commit()  # ✅ Commit transactions

        # ✅ Emit socket event
        for booking in bookings:
            socketio.emit('slot_booked', {
                'slot_id': booking.slot_id,
                'booking_id': booking.id,
                'status': 'booked'
            })

        return jsonify({
            "message": "Direct booking confirmed successfully",
            "bookings": [{"booking_id": b.id, "slot_id": b.slot_id} for b in bookings],
            "transaction_id": transaction.id
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to process direct booking: {str(e)}")
        return jsonify({"message": "Failed to process direct booking", "error": str(e)}), 500

@booking_blueprint.route('/bookings/reject', methods=['POST'])
def reject_booking():
    """Reject a direct booking and handle slot release & repayment."""
    try:
        data = request.json
        booking_id = data.get("booking_id")
        rejection_reason = data.get("rejection_reason", "No reason provided")
        repayment_type = data.get("repayment_type")  # refund, credit, reschedule

        if not booking_id or not repayment_type:
            return jsonify({"message": "booking_id and repayment_type are required"}), 400

        # Fetch booking with transaction details
        booking = db.session.query(Booking).options(joinedload(Booking.transaction)).filter_by(id=booking_id).first()

        if not booking:
            return jsonify({"message": "Booking not found"}), 404

        if not booking.transaction or booking.transaction.booking_type != "direct":
            return jsonify({"message": "Only direct bookings can be rejected"}), 400

        # Fetch slot details
        slot = db.session.query(Slot).filter_by(id=booking.slot_id).first()

        if not slot:
            return jsonify({"message": "Slot not found"}), 404

        # Release slot by updating availability
        db.session.execute(
            text(f"""
                UPDATE VENDOR_{booking.transaction.vendor_id}_SLOT
                SET available_slot = available_slot + 1, is_available = TRUE
                WHERE slot_id = :slot_id AND date = :booked_date
            """),
            {"slot_id": booking.slot_id, "booked_date": booking.transaction.booked_date}
        )

        # Update booking status
        booking.status = "rejected"

        # Create a new refund/credit/reschedule transaction
        new_transaction = Transaction(
            booking_id=booking.id,
            vendor_id=booking.transaction.vendor_id,
            user_id=booking.user_id,
            booked_date=datetime.utcnow().date(),
            booking_time=datetime.utcnow().time(),
            user_name=f"{booking.transaction.user_name} {repayment_type.upper()}-{booking.transaction.id}",
            amount=-booking.transaction.amount,  # Negative amount for refund
            mode_of_payment=booking.transaction.mode_of_payment,
            booking_type=repayment_type,  # refund, credit, reschedule
            settlement_status="processed" if repayment_type == "refund" else "pending"
        )

        db.session.add(new_transaction)
        db.session.commit()

        return jsonify({
            "message": f"Booking {booking_id} rejected successfully",
            "status": booking.status,
            "repayment_type": repayment_type
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to reject booking", "error": str(e)}), 500

@booking_blueprint.route('/bookings/<booking_id>', methods=['GET'])
def get_booking_details(booking_id):
    try:
        # ✅ Fetch Booking
        booking = db.session.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return jsonify({"message": "Booking not found"}), 404

        if booking.status != "confirmed":
            return jsonify({"message": "Booking is not confirmed yet"}), 400

        # ✅ Fetch Slot
        slot = db.session.query(Slot).filter(Slot.id == booking.slot_id).first()
        if not slot:
            return jsonify({"message": "Slot not found"}), 404

        # ✅ Fetch Latest Transaction
        transaction = db.session.query(Transaction).filter(
            Transaction.booking_id == booking.id
        ).order_by(Transaction.id.desc()).first()

        if not transaction:
            return jsonify({"message": "Transaction not found"}), 404

        # ✅ Fetch User
        user = db.session.query(User).filter(User.id == booking.user_id).first()
        if not user:
            return jsonify({"message": "User not found"}), 404

        # ✅ Get Console ID (Fix for multiple rows issue)
        console_entry = db.session.query(available_game_console.c.console_id).filter(
            available_game_console.c.available_game_id == slot.gaming_type_id
        ).first()  # Returns a tuple (console_id,)

        console_id = console_entry[0] if console_entry else None

        # ✅ Fetch Console Details (only if console_id exists)
        console = db.session.query(Console).filter(Console.id == console_id).first() if console_id else None

        # ✅ Fetch Contact Info (Fix incorrect filter syntax)
        contact_info = db.session.query(ContactInfo).filter(
            and_(ContactInfo.parent_id == user.id, ContactInfo.parent_type == 'user')
        ).first()  # Get latest contact info if multiple exist

        # ✅ Format Response
        booking_details = {
            "success": True,
            "booking": {
                "booking_id": f"BK-{booking.id}",  
                "date": transaction.booked_date.strftime("%Y-%m-%d"),
                "time_slot": {
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M")
                },
                "system": console.model_number if console else "Unknown System",
                "customer": {
                    "name": user.name,
                    "email": contact_info.email if contact_info else "",
                    "phone": contact_info.phone if contact_info else ""
                },
                "amount_paid": transaction.amount
            }
        }

        return jsonify(booking_details), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching booking details: {str(e)}"}), 500

@booking_blueprint.route('/update_booking/<int:booking_id>', methods=['PUT'])
def update_booking(booking_id):
    try:
        data = request.json  # Get JSON payload

        # ✅ Fetch existing booking
        booking = db.session.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return jsonify({"message": "Booking not found"}), 404

        available_game_id = db.session.query(AvailableGame).filter(AvailableGame.id == booking.game_id).first()
        # ✅ Fetch transactions linked to booking
        transactions = db.session.query(Transaction).filter(Transaction.booking_id == booking.id).all()

        vendor_id = available_game_id.vendor_id  # Get vendor ID from booking
        booked_date = transactions[0].booked_date  # Assuming transactions have a booked_date, use the first one

        # ✅ Fetch associated slots from `VENDOR_{vendor_id}_SLOT`
        vendor_slot_table = f'VENDOR_{vendor_id}_SLOT'
        existing_slots_query = text(f"SELECT slot_id, is_available FROM {vendor_slot_table} WHERE date = :booked_date AND vendor_id = :vendor_id")
        existing_slots = db.session.execute(existing_slots_query, {
            "booked_date": booked_date, "vendor_id": vendor_id
        }).fetchall()
        existing_slot_ids = {slot.slot_id for slot in existing_slots}


        # ✅ Fetch user details
        user = db.session.query(User).filter(User.id == booking.user_id).first()
        if not user:
            return jsonify({"message": "User not found"}), 404

        # ✅ Fetch user's contact info
        contact_info = db.session.query(ContactInfo).filter(
            and_(ContactInfo.parent_id == user.id, ContactInfo.parent_type == 'user')
        ).order_by(ContactInfo.id.desc()).first()

        # ✅ Use `no_autoflush` to prevent premature flush
        with db.session.no_autoflush:
            # ✅ Update fields if provided
            if "customer" in data:
                user.name = data["customer"].get("name", user.name)
                if contact_info:
                    contact_info.email = data["customer"].get("email", contact_info.email)
                    contact_info.phone = data["customer"].get("phone", contact_info.phone)

            # ✅ If `selected_slots` changed, update slots correctly
            if "selected_slots" in data:
                new_slots_times = set(data["selected_slots"])

                # ✅ Fetch slot IDs for new times from `VENDOR_{vendor_id}_SLOT`
                new_slot_ids = set()
                for time in new_slots_times:
                    start_time = datetime.strptime(time, "%H:%M").time()
                    end_time = (datetime.strptime(time, "%H:%M") + timedelta(minutes=30)).time()

                    slot = db.session.query(Slot).filter(Slot.gaming_type_id == available_game_id.id and Slot.start_time == start_time and Slot.end_time == end_time).first()

                    if not slot:
                        return jsonify({"message": f"Slot {time} is already booked"}), 400
                    
                    new_slot_ids.add(slot.id)

                current_app.logger.info(f"new_slot_ids {new_slot_ids}")

                if new_slot_ids != existing_slot_ids:  # Only proceed if slots are changing
                    # ✅ Step 2: Release old slots by updating availability
                    for slot_id in existing_slot_ids:
                        release_slot_query = text(f"""
                            UPDATE {vendor_slot_table} 
                            SET is_available = TRUE, available_slot = available_slot + 1
                            WHERE slot_id = :slot_id 
                            AND date = :booked_date
                            AND vendor_id = :vendor_id
                        """)
                        db.session.execute(release_slot_query, {
                            "slot_id": slot_id,
                            "booked_date": booked_date,
                            "vendor_id": vendor_id
                        })

                    # ✅ Step 3: Assign new slots by marking as unavailable
                    for slot_id in new_slot_ids:
                        assign_slot_query = text(f"""
                            UPDATE {vendor_slot_table} 
                            SET is_available = FALSE, available_slot = available_slot - 1
                            WHERE slot_id = :slot_id 
                            AND date = :booked_date
                            AND vendor_id = :vendor_id
                        """)
                        db.session.execute(assign_slot_query, {
                            "slot_id": slot_id,
                            "booked_date": booked_date,
                            "vendor_id": vendor_id
                        })

        db.session.commit()  # ✅ Commit changes in one batch

        return jsonify({"message": "Booking updated successfully"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()  # ❌ Rollback on error
        return jsonify({"message": f"Database error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"message": f"Error updating booking: {str(e)}"}), 500


@booking_blueprint.route('/vendor/<int:vendor_id>/bookings', methods=['GET'])
def get_vendor_bookings(vendor_id):
    try:
        # Query bookings for the given vendor
        bookings = (db.session.query(Booking)
                    .join(Slot, Slot.id == Booking.slot_id)
                    .join(AvailableGame, AvailableGame.id == Booking.game_id)
                    .join(Console, Console.id == AvailableGame.console_id)  # assuming AvailableGame has console_id
                    .join(User, User.id == Booking.user_id)
                    .join(ContactInfo, ContactInfo.parent_id == User.id)
                    .filter(AvailableGame.vendor_id == vendor_id)
                    .all())
        
        # Prepare response data
        booking_list = []
        for booking in bookings:
            slot_time = f"{booking.slot.start_time.strftime('%H:%M')} - {booking.slot.end_time.strftime('%H:%M')}"
            system_model_number = booking.game.console.model_number if booking.game.console else None
            user_contact = booking.user.contact_info.phone if booking.user.contact_info else None
            user_email = booking.user.contact_info.email if booking.user.contact_info else None
            booking_list.append({
                "booking_id": booking.id,
                "slot_date": booking.slot.start_time.strftime('%Y-%m-%d'),
                "slot_time": slot_time,
                "system_model_number": system_model_number,
                "user_name": booking.user.name,
                "user_email": user_email,
                "user_contact": user_contact,
                "status": booking.status,
                "booking_type": "hash"  # Assuming a static value for booking type
            })
        
        # Return response as JSON
        return jsonify({"bookings": booking_list}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@booking_blueprint.route('/newBooking/vendor/<int:vendor_id>', methods=['POST'])
def new_booking(vendor_id):
    """
    Creates a new booking for the given vendor, checking for existing users or creating a new one.
    """
    try:
        current_app.logger.info("New Booking Triggered")
        data = request.json

        console_type = data.get("consoleType")
        name = data.get("name")
        email = data.get("email")
        phone = data.get("phone")
        booked_date = data.get("bookedDate")
        slot_ids = data.get("slotId")  # List of slot IDs
        payment_type = data.get("paymentType")
        console_id = data.get("consoleId")
        is_rapid_booking = data.get("isRapidBooking")

        if not all([name, email, phone, booked_date, slot_ids, payment_type]):
            return jsonify({"message": "Missing required fields"}), 400

        # Check if user already exists
        user = db.session.query(User).join(ContactInfo).filter(ContactInfo.email == email).first()

        if not user:
            # Create a new user
            user = User(
                fid=email,
                avatar_path="Not defined",
                name=name,
                game_username=name.lower().replace(" ", "_"),
                parent_type="user"
            )

            contact_info = ContactInfo(
                phone=phone,
                email=email,
                parent_id=user.id,
                parent_type="user"
            )

            user.contact_info = contact_info

            db.session.add(user)
            db.session.flush()

        # Fetch the available game details
        available_game = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).first()

        if not available_game:
            return jsonify({"message": "Game not found for this vendor"}), 404

        # Check slot availability for all requested slots
        placeholders = ", ".join([f":slot_id_{i}" for i in range(len(slot_ids))])
        slot_params = {f"slot_id_{i}": slot_id for i, slot_id in enumerate(slot_ids)}

        slot_entries = db.session.execute(
            text(f"""
                SELECT slot_id, available_slot, is_available
                FROM VENDOR_{vendor_id}_SLOT
                WHERE slot_id IN ({placeholders})
                AND date = :booked_date
            """),
            {"booked_date": booked_date, **slot_params}
        ).fetchall()

        # Ensure all requested slots exist and are available
        if len(slot_entries) != len(slot_ids):
            return jsonify({"message": "One or more slots not found or unavailable"}), 400

        for slot in slot_entries:
            if slot[1] <= 0 or not slot[2]:  # available_slot <= 0 or is_available = False
                return jsonify({"message": f"Slot {slot[0]} is fully booked"}), 400

        # Begin transaction
        bookings = []
        for slot_id in slot_ids:
            slot_obj = db.session.query(Slot).filter_by(id=slot_id).first()
            available_game = db.session.query(AvailableGame).filter_by(id=slot_obj.gaming_type_id).first()
            
            booking = Booking(
                slot_id=slot_id,
                game_id=available_game.id,
                user_id=user.id,
                status="confirmed"
            )
            db.session.add(booking)
            db.session.flush()  # Get the booking ID
            bookings.append(booking)

        # Decrease available slot count for all booked slots
        db.session.execute(
            text(f"""
                UPDATE VENDOR_{vendor_id}_SLOT
                SET available_slot = available_slot - 1,
                    is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                WHERE slot_id IN ({placeholders})
                AND date = :booked_date;
            """),
            {"booked_date": booked_date, **slot_params}
        )

        db.session.commit()  # Commit all bookings before creating transactions

        # Create transactions for each booking
        transactions = []
        for booking in bookings:
            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor_id,
                user_id=user.id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                amount=available_game.single_slot_price,
                mode_of_payment=payment_type,
                booking_type="direct",
                settlement_status="NA" if payment_type != "paid" else "completed"
            )
            db.session.add(transaction)
            transactions.append(transaction)

        if is_rapid_booking:
            # ✅ Define the dynamic console availability table name
            console_table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"

            # ✅ Update the status to false (occupied)
            sql_update_status = text(f"""
                UPDATE {console_table_name}
                SET is_available = FALSE
                WHERE console_id = :console_id AND game_id = :game_id
            """)

            db.session.execute(sql_update_status, {
                "console_id": console_id,
                "game_id": available_game.id
            })
        
        db.session.commit()

        socketio = current_app.extensions['socketio']

        # Emit event for each booked slot
        for booking in bookings:
            socketio.emit('slot_booked', {
                'slot_id': booking.slot_id,
                'booking_id': booking.id,
                'status': 'booked'
            })

        for trans in transactions:
            console_id_val = console_id if console_id is not None else -1
            BookingService.insert_into_vendor_dashboard_table(trans.id, console_id_val)
            
        return jsonify({
            "message": "Booking confirmed successfully",
            "booking_ids": [b.id for b in bookings],
            "transaction_ids": [t.id for t in transactions]
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to process booking: {str(e)}")
        return jsonify({"message": "Failed to process booking", "error": str(e)}), 500

@booking_blueprint.route('/getAllBooking/vendor/<int:vendor_id>/<string:date>/', methods=['GET'])
def get_all_booking(vendor_id, date):
    """
    Retrieves all booking details for a given vendor from the given date onwards.
    """
    try:
        current_app.logger.info("Fetching all bookings for vendor_id=%s from date=%s onwards", vendor_id, date)

        # Convert date format (YYYYMMDD → YYYY-MM-DD)
        formatted_date = datetime.strptime(date, "%Y%m%d").date()

        # Query to fetch booking details for given vendor from the date onwards
        results = db.session.query(
            Booking.id.label("bookingId"),
            Transaction.booked_date.label("bookingDate"),
            Transaction.booking_time.label("bookingTime"),
            User.name.label("userName"),
            AvailableGame.game_name.label("consoleType"),
            AvailableGame.id.label("consoleTypeId"),
            Transaction.booked_date.label("bookedDate"),
            Slot.start_time.label("startTime"),
            Slot.end_time.label("endTime"),
            Booking.status.label("status"),
            Transaction.booking_type.label("type")
        ).join(Transaction, Booking.id == Transaction.booking_id) \
         .join(User, Booking.user_id == User.id) \
         .join(AvailableGame, Booking.game_id == AvailableGame.id) \
         .join(Slot, Booking.slot_id == Slot.id) \
         .filter(Transaction.vendor_id == vendor_id, Transaction.booked_date >= formatted_date) \
         .order_by(Transaction.booked_date.asc()) \
         .all()

        # Convert results into a structured list
        bookings = [{
            "bookingId": row.bookingId,
            "bookingDate": row.bookingDate.strftime("%Y-%m-%d"),
            "bookingTime": row.bookingTime.strftime("%H:%M:%S"),
            "userName": row.userName,
            "consoleType": row.consoleType,
            "consoleTypeId": row.consoleTypeId,
            "bookedDate": row.bookedDate.strftime("%Y-%m-%d"),
            "startTime": row.startTime.strftime("%H:%M:%S"),
            "endTime": row.endTime.strftime("%H:%M:%S"),
            "status": row.status,
            "type": row.type
        } for row in results]

        return jsonify(bookings), 200

    except Exception as e:
        current_app.logger.error(f"Failed to fetch bookings: {str(e)}")
        return jsonify({"message": "Failed to fetch bookings", "error": str(e)}), 500
