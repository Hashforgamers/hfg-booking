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
from models.voucher import Voucher
from models.voucherRedemptionLog import VoucherRedemptionLog
from models.paymentTransactionMapping import PaymentTransactionMapping
from models.userHashCoin import UserHashCoin
from models.accessBookingCode import AccessBookingCode

from sqlalchemy.sql import text
from sqlalchemy.orm import joinedload

from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, distinct
from services.mail_service import booking_mail, reject_booking_mail, extra_booking_time_mail

from models.hashWallet import HashWallet
from models.hashWalletTransaction import HashWalletTransaction

from utils.common import generate_fid, generate_access_code

booking_blueprint = Blueprint('bookings', __name__)

@booking_blueprint.route('/bookings', methods=['POST'])
def create_booking():
    current_app.logger.info(f"Current App in Blueprint {current_app}")
    data = request.json
    slot_ids = data.get("slot_id")  # Now expects a list
    user_id = data.get("user_id")
    game_id = data.get("game_id")
    book_date = data.get("book_date")

    if not slot_ids or not user_id or not game_id or not book_date:
        return jsonify({"message": "slot_id, game_id, user_id, and book_date are required"}), 400

    try:
        socketio = current_app.extensions['socketio']
        scheduler = current_app.extensions['scheduler']
        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()
        booking_ids = []

        for slot_id in slot_ids:
            slot_entry = db.session.execute(text(f"""
                SELECT available_slot, is_available
                FROM VENDOR_{available_game.vendor_id}_SLOT
                WHERE slot_id = :slot_id AND date = :book_date
            """), {"slot_id": slot_id, "book_date": book_date}).fetchone()

            if slot_entry is None or slot_entry[0] <= 0 or not slot_entry[1]:
                continue  # Skip if not available

            booking = BookingService.create_booking(slot_id, game_id, user_id, socketio, book_date)
            db.session.flush()
            booking_ids.append(booking.id)

            scheduler.enqueue_in(
                timedelta(seconds=360),
                BookingService.release_slot,
                slot_id,
                booking.id,
                book_date
            )

        db.session.commit()

        if not booking_ids:
            return jsonify({"message": "No slots available for booking"}), 400

        return jsonify({"message": "Slots frozen", "booking_ids": booking_ids}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to freeze slot(s)", "error": str(e)}), 500

@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    try:
        data = request.get_json(force=True)
        booking_ids = data.get('booking_id')  # Expects a list
        payment_id = data.get('payment_id')   # Optional
        book_date = data.get('book_date')
        voucher_code = data.get("voucher_code")
        mode = data.get("payment_mode", "payment_gateway")  # Default to payment_gateway

        if not booking_ids:
            return jsonify({'message': 'No booking IDs provided'}), 400

        confirmed_ids = []

        # Generate access code for the booking session
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()  # Get access_code_entry.id

        for booking_id in booking_ids:
            booking = db.session.query(Booking).filter_by(id=booking_id).first()
            if not booking or booking.status == 'confirmed':
                continue

            booking.status = 'confirmed'
            booking.updated_at = datetime.utcnow()
            booking.access_code_id = access_code_entry.id

            available_game = db.session.query(AvailableGame).filter_by(id=booking.game_id).first()
            vendor = db.session.query(Vendor).filter_by(id=available_game.vendor_id).first() if available_game else None
            slot_obj = db.session.query(Slot).filter_by(id=booking.slot_id).first()
            user = db.session.query(User).filter_by(id=booking.user_id).first()

            if not all([available_game, vendor, slot_obj, user]):
                continue

            # Handle voucher if provided
            voucher = None
            if voucher_code:
                voucher = db.session.query(Voucher).filter_by(code=voucher_code, user_id=user.id, is_active=True).first()
                if not voucher:
                    return jsonify({'message': 'Invalid or expired voucher'}), 400

            # Credit reward coins
            user_hash_coin = db.session.query(UserHashCoin).filter_by(user_id=user.id).first()
            if not user_hash_coin:
                user_hash_coin = UserHashCoin(user_id=user.id, hash_coins=0)
                db.session.add(user_hash_coin)
            user_hash_coin.hash_coins += 1000

            # Pricing & discount
            slot_price = available_game.single_slot_price
            discount_percentage = voucher.discount_percentage if voucher else 0
            discount_amount = int(slot_price * discount_percentage / 100)
            amount = slot_price - discount_amount

            # Payment via wallet or gateway
            if mode == "wallet":
                try:
                    BookingService.debit_wallet(user.id, booking.id, amount)
                    payment_mode_used = "wallet"
                except ValueError as e:
                    return jsonify({"message": str(e)}), 400
            else:
                payment_mode_used = "payment_gateway"

            # Create transaction
            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor.id,
                user_id=user.id,
                user_name=user.name,
                original_amount=slot_price,
                discounted_amount=discount_amount,
                amount=amount,
                mode_of_payment=payment_mode_used,
                booking_date=datetime.utcnow().date(),
                booked_date=book_date,
                booking_time=datetime.utcnow().time()
            )
            db.session.add(transaction)
            db.session.flush()

            # Save payment mapping if available
            if payment_id:
                BookingService.save_payment_transaction_mapping(booking.id, transaction.id, payment_id)

            # Mark voucher as used
            if voucher:
                voucher.is_active = False
                db.session.add(VoucherRedemptionLog(
                    user_id=user.id,
                    voucher_id=voucher.id,
                    booking_id=booking.id
                ))

            # Update vendor slot table
            db.session.execute(text(f"""
                UPDATE VENDOR_{vendor.id}_SLOT
                SET available_slot = available_slot - 1,
                    is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                WHERE slot_id = :slot_id AND date = :book_date
            """), {
                "slot_id": booking.slot_id,
                "book_date": book_date
            })

            # Insert into vendor dashboard and promo table
            BookingService.insert_into_vendor_dashboard_table(transaction.id, -1)
            BookingService.insert_into_vendor_promo_table(transaction.id, -1)

            # Send email confirmation
            booking_mail(
                gamer_name=user.name,
                gamer_phone=user.contact_info.phone,
                gamer_email=user.contact_info.email,
                cafe_name=vendor.cafe_name,
                booking_date=datetime.utcnow().strftime("%Y-%m-%d"),
                booked_for_date=str(book_date),
                booking_details=[{
                    "booking_id": booking.id,
                    "slot_time": f"{slot_obj.start_time} - {slot_obj.end_time}"
                }],
                price_paid=amount
            )

            confirmed_ids.append(booking.id)

        db.session.commit()
        return jsonify({'message': 'Bookings confirmed successfully', 'confirmed_ids': confirmed_ids}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error confirming booking")

        # Unfreeze slots
        try:
            booking_ids = data.get('booking_id')
            book_date = data.get('book_date')

            for booking_id in booking_ids or []:
                booking = db.session.query(Booking).filter_by(id=booking_id).first()
                if not booking or booking.status == 'confirmed':
                    continue

                booking.status = 'cancelled'
                booking.updated_at = datetime.utcnow()

                available_game = db.session.query(AvailableGame).filter_by(id=booking.game_id).first()
                if available_game:
                    vendor_id = available_game.vendor_id
                    db.session.execute(text(f"""
                        UPDATE VENDOR_{vendor_id}_SLOT
                        SET available_slot = available_slot + 1,
                            is_available = TRUE
                        WHERE slot_id = :slot_id AND date = :book_date
                    """), {
                        "slot_id": booking.slot_id,
                        "book_date": book_date
                    })
            db.session.commit()
        except Exception as cleanup_error:
            current_app.logger.error(f"Error during slot unfreezing cleanup: {str(cleanup_error)}")

        return jsonify({'error': str(e)}), 500

@booking_blueprint.route('/redeem-voucher', methods=['POST'])
def redeem_voucher():
    data = request.json
    user_id = data.get('user_id')
    discount = data.get('discount_percentage')  # expected: 10, 20, 30

    if discount not in [10, 20, 30]:
        return jsonify({"message": "Invalid discount value"}), 400

    required_coins = discount * 1000  # 10% = 10k coins, 20% = 20k, etc.

    user_hash_coin = db.session.query(UserHashCoin).filter_by(user_id=user_id).first()
    if not user_hash_coin or user_hash_coin.hash_coins < required_coins:
        return jsonify({"message": "Not enough Hash Coins"}), 400

    # Deduct coins
    user_hash_coin.hash_coins -= required_coins

    # Generate unique voucher code
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    voucher = Voucher(
        code=code,
        user_id=user_id,
        discount_percentage=discount,
        is_active=True
    )
    db.session.add(voucher)
    db.session.commit()

    return jsonify({
        "message": f"{discount}% voucher created successfully",
        "voucher_code": code,
        "hash_coins_remaining": user_hash_coin.hash_coins
    }), 200

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
                original_amount=available_game.single_slot_price,
                discounted_amount=0,
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
        user_email = data.get("user_email")

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
            original_amount=-booking.transaction.amount,
            discounted_amount=0,
            amount=-booking.transaction.amount,  # Negative amount for refund
            mode_of_payment=booking.transaction.mode_of_payment,
            booking_type=repayment_type,  # refund, credit, reschedule
            settlement_status="processed" if repayment_type == "refund" else "pending"
        )

        db.session.add(new_transaction)
        db.session.commit()

        BookingService.update_dashboard_booking_status(booking.transaction.id, booking.transaction.vendor_id, "rejected")

        vendor_contact = ContactInfo.query.filter_by(parent_id=booking.transaction.vendor_id, parent_type="vendor").first()
        vendor = Vendor.query.filter_by(id=booking.transaction.vendor_id).first()

        current_app.logger.info(
            f"gamer Email {user_email}; gamer name :{booking.transaction.user_name}; cafe_name: {vendor_contact.email if vendor_contact else 'N/A'} ; rejection {rejection_reason}"
        )

        # Send rejection email
        reject_booking_mail(
            gamer_name=booking.transaction.user_name,
            gamer_email=user_email,
            cafe_name=vendor.cafe_name if vendor else "N/A",
            reason=rejection_reason
        )

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
                "game_id": booking.game_id,
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
        booking_type = data.get("bookingType")
        # Extract user_id safely from the data
        user_id = data.get("userId") if data.get("userId") is not None else None

        dashboard_status = None

        if booking_type is None:
            booking_type = "direct"

        if not all([name, phone, booked_date, slot_ids, payment_type]):
            return jsonify({"message": "Missing required fields"}), 400

        # Check if user already exists
        if user_id is not None:
            user = db.session.query(User).filter(User.id == user_id).first()
        else:
            user = db.session.query(User).join(ContactInfo).filter(ContactInfo.email == email).first()

        if not user:
            # Create a new user
            user = User(
                fid=generate_fid(),
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
        
         # 1. Generate new access code
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()  # ensure access_code_entry.id is populated

        for slot_id in slot_ids:
            slot_obj = db.session.query(Slot).filter_by(id=slot_id).first()
            available_game = db.session.query(AvailableGame).filter_by(id=slot_obj.gaming_type_id).first()
        
            booking = Booking(
                slot_id=slot_id,
                game_id=available_game.id,
                user_id=user.id,
                status="confirmed",
                access_code_id=access_code_entry.id
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
                original_amount=available_game.single_slot_price,
                discounted_amount = 0,
                amount=available_game.single_slot_price,
                mode_of_payment=payment_type,
                booking_type=booking_type,
                settlement_status="NA" if payment_type != "paid" else "completed"
            )
            db.session.add(transaction)
            transactions.append(transaction)

        if is_rapid_booking:
            dashboard_status = "current"

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
            BookingService.insert_into_vendor_dashboard_table(trans.id, console_id_val, dashboard_status),
            BookingService.insert_into_vendor_promo_table(trans.id, console_id_val)

        # Extract slot times for the email
        booking_details = []
        for booking in bookings:
            slot_obj = db.session.query(Slot).filter_by(id=booking.slot_id).first()
            if slot_obj:
                slot_time = f"{str(slot_obj.start_time)} - {str(slot_obj.end_time)}"  # Format as start_time - end_time
            else:
                slot_time = 'N/A'  # In case slot_obj is None (just as a fallback)
            
            booking_details.append({
                "booking_id": booking.id,
                "slot_time": slot_time
            })

        # Send confirmation email
        cafe_name = db.session.query(Vendor).filter_by(id=vendor_id).first().cafe_name
        booking_mail(
            gamer_name=name,
            gamer_phone=phone,
            gamer_email=email,
            cafe_name=cafe_name,
            booking_date=datetime.utcnow().strftime("%Y-%m-%d"),
            booked_for_date=booked_date,
            booking_details=booking_details,
            price_paid=available_game.single_slot_price
        )

        return jsonify({
            "message": "Booking confirmed successfully",
            "booking_ids": [b.id for b in bookings],
            "transaction_ids": [t.id for t in transactions]
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to process booking: {str(e)}")
        return jsonify({"message": "Failed to process booking", "error": str(e)}), 500

@booking_blueprint.route('/extraBooking', methods=['POST'])
def extra_booking():
    """
    Records extra booking (time extended) played by the user in a gaming cafe.
    """
    try:
        data = request.json

        required_fields = ["consoleNumber", "consoleType", "date", "slotId", "userId", "username", "amount", "gameId", "modeOfPayment","vendorId"]
        if not all(data.get(field) is not None for field in required_fields):
            return jsonify({"message": "Missing required fields"}), 400

        # Extract values
        console_number = data["consoleNumber"]
        console_type = data["consoleType"]
        booked_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        slot_id = data["slotId"]
        user_id = data["userId"]
        username = data["username"]
        amount = data["amount"]
        game_id = data["gameId"]
        mode_of_payment = data["modeOfPayment"]
        vendor_id = data["vendorId"] 

        # Optional: verify user and slot exist
        user = db.session.query(User).filter_by(id=user_id).first()
        slot = db.session.query(Slot).filter_by(id=slot_id).first()

        if not user or not slot:
            return jsonify({"message": "User or slot not found"}), 404

        # Create a record in Booking table for extra booking (status='extra')
        extra_booking = Booking(
            slot_id=slot_id,
            game_id=game_id,
            user_id=user_id,
            status="extra"
        )
        db.session.add(extra_booking)
        db.session.flush()

        # Create a transaction for extra booking
        transaction = Transaction(
            booking_id=extra_booking.id,
            vendor_id=vendor_id,
            user_id=user_id,
            booked_date=booked_date,
            booking_time=datetime.utcnow().time(),
            user_name=username,
            original_amount=amount,
            discounted_amount=0,
            amount=amount,
            mode_of_payment=mode_of_payment,
            booking_type="extra",
            settlement_status="completed" if mode_of_payment == "paid" else "NA"
        )
        db.session.add(transaction)
        db.session.commit()

        # Optional: Push to dashboard/promo tables
        BookingService.insert_into_vendor_dashboard_table(transaction.id, console_number)
        BookingService.insert_into_vendor_promo_table(transaction.id, console_number)

        # Fallback if user or email not found
        gamer_email = user.contact_info.email if user and user.contact_info else "no-reply@example.com"

        if not slot or not slot.start_time or not slot.end_time:
            slot_time_str = "N/A"
        else:
            slot_time_str = f"{slot.start_time.strftime('%-I:%M %p')} to {slot.end_time.strftime('%-I:%M %p')}"
            # Use '%#I' on Windows instead of '%-I' for removing leading zeros
            
        # ✅ Send the extra booking email
        extra_booking_time_mail(
            username=username,
            user_email=gamer_email,
            booked_date=booked_date.strftime("%Y-%m-%d"),
            slot_time=slot_time_str,
            console_type=console_type,
            console_number=console_number,
            amount=amount,
            mode_of_payment=mode_of_payment
        )

        return jsonify({
            "message": "Extra booking recorded successfully",
            "booking_id": extra_booking.id,
            "transaction_id": transaction.id
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error recording extra booking: {str(e)}")
        return jsonify({"message": "Failed to record extra booking", "error": str(e)}), 500

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
            Transaction.booking_type.label("type"),
            Transaction.user_id.label("userId"),
            Transaction.booked_date.label("bookedDate")
        ).join(Transaction, Booking.id == Transaction.booking_id) \
         .join(User, Booking.user_id == User.id) \
         .join(AvailableGame, Booking.game_id == AvailableGame.id) \
         .join(Slot, Booking.slot_id == Slot.id) \
         .filter(Transaction.vendor_id == vendor_id, Transaction.booked_date >= formatted_date) \
         .distinct(Booking.id) \
         .order_by(Booking.id, Transaction.booking_time.desc()) \
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
            "type": row.type,
            "userId":row.userId,
            "bookedDate":row.bookedDate
        } for row in results]

        return jsonify(bookings), 200

    except Exception as e:
        current_app.logger.error(f"Failed to fetch bookings: {str(e)}")
        return jsonify({"message": "Failed to fetch bookings", "error": str(e)}), 500

@booking_blueprint.route('/vendor/<string:vendor_id>/users', methods=['GET'])
def get_user_details(vendor_id):
    try:
        table_name = f"VENDOR_{vendor_id}_DASHBOARD"

        # Step 1: Get all unique user_ids from the vendor dashboard table
        user_id_query = text(f"""
            SELECT DISTINCT user_id FROM {table_name}
        """)
        result = db.session.execute(user_id_query)
        user_ids = [row[0] for row in result]

        if not user_ids:
            return jsonify({"message": "No users found for this vendor."}), 404

        # Step 2: Fetch User and ContactInfo
        users = User.query.filter(User.id.in_(user_ids)).all()

        user_list = []
        for user in users:
            contact = ContactInfo.query.filter_by(parent_id=user.id, parent_type="user").first()
            
            user_data = {
                "id": user.id,
                "name": user.name,
                "game_username": user.game_username,
                "avatar_path": user.avatar_path,
                "gender": user.gender,
                "dob": user.dob.isoformat() if user.dob else None,
                "email": contact.email if contact else None,
                "phone": contact.phone if contact else None
            }
            user_list.append(user_data)

        return jsonify(user_list), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching user details: {e}")
        return jsonify({"error": str(e)}), 500

@booking_blueprint.route('/vendor/<string:vendor_id>/getConsoleStatus/<int:console_id>', methods=['GET'])
def get_console_status(vendor_id, console_id):
    """Retrieve the availability status of a specific console for a vendor."""
    try:
        table_name = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"

        # Construct SQL to get console details
        sql = text(f"""
            SELECT vendor_id, console_id, game_id, is_available
            FROM {table_name}
            WHERE console_id = :console_id
        """)

        result = db.session.execute(sql, {'console_id': console_id}).fetchall()

        if not result:
            return jsonify({"message": "Console not found."}), 404

        consoles = [
            {
                "vendor_id": row.vendor_id,
                "console_id": row.console_id,
                "game_id": row.game_id,
                "is_available": row.is_available
            } for row in result
        ]

        return jsonify(consoles), 200

    except Exception as e:
        current_app.logger.error(f"Error retrieving console status: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500
