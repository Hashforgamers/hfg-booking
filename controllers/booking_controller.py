from flask import Blueprint, request, jsonify, current_app, g
from services.booking_service import BookingService
from db.extensions import db
from models.slot import Slot
from models.booking import Booking
from models.booking import Booking
import logging
import random
import os
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
from models.bookingExtraService  import BookingExtraService
from models.extraServiceCategory import ExtraServiceCategory
from models.extraServiceMenu import ExtraServiceMenu
from models.userPass import UserPass
from datetime import datetime, timedelta, timezone
import pytz
from flask import current_app, jsonify
from sqlalchemy.orm import joinedload

IST = pytz.timezone("Asia/Kolkata")

from sqlalchemy.sql import text
from sqlalchemy.orm import joinedload
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, distinct
from services.mail_service import booking_mail, reject_booking_mail, extra_booking_time_mail

from models.hashWallet import HashWallet
from models.hashWalletTransaction import HashWalletTransaction
import time
import json
import base64
import requests
import hmac
import hashlib
import razorpay
from services.security import auth_required_self

import uuid

from utils.common import generate_fid, generate_access_code, get_razorpay_keys

booking_blueprint = Blueprint('bookings', __name__)

@booking_blueprint.route('/create_order', methods=['POST'])
def create_order():
    data = request.get_json()

    amount = data.get('amount')  # in paisa
    currency = data.get('currency', 'INR')
    receipt = data.get('receipt', f'order_rcpt_{int(time.time())}')

    RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Basic " + base64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
    }

    payload = {
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1
    }

    response = requests.post("https://api.razorpay.com/v1/orders", headers=headers, json=payload)

    if response.ok:
        return jsonify(response.json()), 200

    # For production, just forward the error status and message from Razorpay without exposing internal details
    return jsonify({"error": "Order creation failed"}), response.status_code

@booking_blueprint.route('/capture_payment', methods=['POST'])
def capture_payment():
    data = request.get_json()
    payment_id = data.get('razorpay_payment_id')
    order_id = data.get('razorpay_order_id')
    signature = data.get('razorpay_signature')

    if not payment_id or not order_id or not signature:
        return jsonify({"message": "Missing payment details"}), 400

    RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")

    # Validate signature
    msg = f"{order_id}|{payment_id}"
    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    if generated_signature != signature:
        return jsonify({"message": "Invalid payment signature"}), 400

    # Initialize Razorpay client
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    try:
        # Fetch payment to check status
        payment = razorpay_client.payment.fetch(payment_id)

        if payment['status'] == 'authorized':
            # Capture payment manually if not auto-captured during order creation
            amount = payment['amount']  # amount in paisa
            razorpay_client.payment.capture(payment_id, amount)
            return jsonify({"message": "Payment captured successfully"}), 200

        elif payment["status"] == "captured":
            return jsonify({"message": "Payment already captured"}), 200

        else:
            return jsonify({"message": f"Payment status {payment['status']} - cannot capture."}), 400
    except razorpay.errors.RazorpayError as e:
        current_app.logger.error(f"Razorpay error during capture: {str(e)}")
        return jsonify({"message": "Error capturing payment", "error": str(e)}), 500

@booking_blueprint.route('/bookings', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def create_booking():
    # Correlation id for this request
    g.cid = getattr(g, "cid", None) or str(uuid.uuid4())
    cid = g.cid
    log = current_app.logger

    try:
        user_id = g.auth_user_id
    except Exception:
        user_id = None

    log.info("bookings.post.start cid=%s user_id=%s", cid, user_id)

    data = request.json or {}
    slot_ids = data.get("slot_id")  # list expected
    game_id = data.get("game_id")
    book_date = data.get("book_date")

    log.info("bookings.post.payload cid=%s slot_ids_len=%s game_id=%s book_date=%s",
             cid, (len(slot_ids) if isinstance(slot_ids, list) else None), game_id, book_date)

    if not slot_ids or not user_id or not game_id or not book_date:
        log.warning("bookings.post.validation_failed cid=%s", cid)
        return jsonify({"message": "slot_id, game_id, user_id, and book_date are required"}), 400

    try:
        socketio = current_app.extensions.get('socketio')
        scheduler = current_app.extensions.get('scheduler')
        log.info("bookings.post.extensions cid=%s has_socketio=%s has_scheduler=%s",
                 cid, bool(socketio), bool(scheduler))

        available_game = db.session.query(AvailableGame).filter(AvailableGame.id == game_id).first()
        if not available_game:
            log.warning("bookings.post.available_game_missing cid=%s game_id=%s", cid, game_id)
            return jsonify({"message": "Game not found"}), 404

        vendor_id = available_game.vendor_id
        log.info("bookings.post.vendor_resolved cid=%s vendor_id=%s", cid, vendor_id)

        booking_mappings = []
        processed = 0
        skipped = 0

        for slot_id in slot_ids:
            processed += 1
            try:
                log.info("bookings.post.slot_check.start cid=%s slot_id=%s", cid, slot_id)

                slot_entry = db.session.execute(text(f"""
                    SELECT available_slot, is_available
                    FROM VENDOR_{vendor_id}_SLOT
                    WHERE slot_id = :slot_id AND date = :book_date
                """), {"slot_id": slot_id, "book_date": book_date}).fetchone()

                log.info("bookings.post.slot_check.result cid=%s slot_id=%s has_entry=%s entry=%s",
                         cid, slot_id, bool(slot_entry), (tuple(slot_entry) if slot_entry else None))

                if slot_entry is None or slot_entry[0] <= 0 or not slot_entry:
                    skipped += 1
                    log.info("bookings.post.slot_skipped cid=%s slot_id=%s reason=%s",
                             cid, slot_id,
                             ("no_entry" if slot_entry is None else ("no_slots" if slot_entry <= 0 else "not_available")))
                    continue

                booking = BookingService.create_booking(slot_id, game_id, user_id, socketio, book_date)
                db.session.flush()

                log.info("bookings.post.slot_booked cid=%s slot_id=%s booking_id=%s",
                         cid, slot_id, booking.id)

                booking_mappings.append({
                    "slot_id": slot_id,
                    "booking_id": booking.id
                })

                if scheduler:
                    scheduler.enqueue_in(
                        timedelta(seconds=360),
                        BookingService.release_slot,
                        slot_id,
                        booking.id,
                        book_date
                    )
                    log.info("bookings.post.release_scheduled cid=%s slot_id=%s booking_id=%s delay_sec=%s",
                             cid, slot_id, booking.id, 360)

            except Exception as loop_err:
                # Do not abort the entire batch; record and continue
                log.exception("bookings.post.slot_error cid=%s slot_id=%s error=%s", cid, slot_id, loop_err)
                continue

        try:
            db.session.commit()
            log.info("bookings.post.db_committed cid=%s bookings_count=%s skipped=%s processed=%s",
                     cid, len(booking_mappings), skipped, processed)
        except Exception as commit_err:
            db.session.rollback()
            log.exception("bookings.post.db_commit_failed cid=%s error=%s", cid, commit_err)
            return jsonify({"message": "Failed to freeze slot(s)", "error": "commit_failed"}), 500

        if not booking_mappings:
            log.info("bookings.post.none_booked cid=%s", cid)
            return jsonify({"message": "No slots available for booking"}), 400

        log.info("bookings.post.success cid=%s bookings=%s", cid, booking_mappings)
        return jsonify({
            "message": "Slots frozen",
            "bookings": booking_mappings
        }), 200

    except Exception as e:
        db.session.rollback()
        log.exception("bookings.post.failed cid=%s error=%s", cid, e)
        return jsonify({"message": "Failed to freeze slot(s)", "error": str(e)}), 500

@booking_blueprint.route('/release_slot', methods=['POST'])
def release_slot():
    try:
        data = request.json
        bookings = data.get("bookings")  # Expect a list of {slot_id, booking_id, book_date}

        if not bookings or not isinstance(bookings, list):
            return jsonify({"message": "A list of bookings is required under the 'bookings' key."}), 400

        errors = []
        success_count = 0

        for index, booking in enumerate(bookings):
            slot_id = booking.get("slot_id")
            booking_id = booking.get("booking_id")
            book_date = booking.get("book_date")

            if not slot_id or not booking_id or not book_date:
                errors.append({"index": index, "error": "slot_id, booking_id, and book_date are required"})
                continue

            # Validate date format
            try:
                datetime.strptime(book_date, '%Y-%m-%d')
            except ValueError:
                errors.append({"index": index, "error": "book_date must be in YYYY-MM-DD format"})
                continue

            try:
                BookingService.release_slot(slot_id, booking_id, book_date)
                success_count += 1
            except Exception as e:
                errors.append({"index": index, "error": f"Failed to release slot: {str(e)}"})

        db.session.commit()

        response = {"message": f"Processed {success_count} bookings."}
        if errors:
            response["errors"] = errors
            return jsonify(response), 207  # 207 Multi-Status for partial success
        else:
            return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to release slot(s)", "error": str(e)}), 500

@booking_blueprint.route('/generate_payment_link', methods=['POST'])
def generate_payment_link():
    """
    Creates a Razorpay Payment Link and returns the URL.
    Expects JSON: { "amount": 500, "customer_email": "user@example.com", "customer_contact": "9876543210" }
    Amount is expected in rupees.
    """
    data = request.get_json()
    amount_rupees = data.get('amount')
    customer_email = data.get('customer_email')
    customer_contact = data.get('customer_contact')

    if not (amount_rupees and customer_email and customer_contact):
        return jsonify({"message": "Missing required fields!"}), 400

    try:
        amount_paise = int(float(amount_rupees) * 100)
    except Exception:
        return jsonify({"message": "Invalid amount format."}), 400

    RAZORPAY_KEY_ID = current_app.config.get('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET = current_app.config.get('RAZORPAY_KEY_SECRET')
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        return jsonify({'message': 'Server config error.'}), 500

    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    payment_link_data = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": "Payment for your order",
        "customer": {
            "name": "Customer Name",  # Optional, add if you have it
            "contact": customer_contact,
            "email": customer_email
        },
        "notify": {
            "sms": True,
            "email": True
        },
        "reminder_enable": True,
        "callback_method": "get"  # Or "post" if you handle a callback
    }

    try:
        payment_link = client.payment_link.create(payment_link_data)
        return jsonify({
            'payment_link': payment_link['short_url'],
            'id': payment_link['id'],
            'status': payment_link['status']
        })
    except Exception as e:
        return jsonify({'message': 'Error creating payment link', 'error': str(e)}), 500

@booking_blueprint.route('/bookings/confirm', methods=['POST'])
def confirm_booking():
    try:
        data = request.get_json(force=True)

        booking_ids         = data.get('booking_id')  # list[int]
        payment_id          = data.get('payment_id')  # Razorpay payment id
        book_date_str       = data.get('book_date')
        voucher_code        = data.get('voucher_code')
        payment_mode        = data.get('payment_mode', "payment_gateway")
        use_pass            = bool(data.get('use_pass', False))
        user_pass_id        = data.get('user_pass_id')  # <-- New param
        extra_services_list = data.get('extra_services', [])  # [{category_id, item_id, quantity}]

        current_app.logger.info(f"Confirm payload: {data}")

        # Basic validation
        if not booking_ids or not book_date_str:
            return jsonify({'message': 'booking_id and book_date are required'}), 400
        if use_pass and not user_pass_id:
            return jsonify({'message': 'user_pass_id is required when use_pass=true'}), 400

        # Parse book_date
        try:
            if 'T' in book_date_str:
                book_date = datetime.fromisoformat(book_date_str).date()
            else:
                book_date = datetime.strptime(book_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"message": "Invalid book_date format"}), 400

        # Setup Razorpay client
        RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
        RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        razorpay_payment_verified = True

        # Verify Razorpay payment if using gateway
        if payment_mode == "payment_gateway":
            if not payment_id:
                return jsonify({"message": "payment_id required for payment_gateway mode"}), 400
            try:
                payment = razorpay_client.payment.fetch(payment_id)
                current_app.logger.info(f"Razorpay payment fetched: {payment}")
                if payment['status'] == 'captured':
                    razorpay_payment_verified = True
                else:
                    return jsonify({"message": "Payment not successful or not captured"}), 400
            except razorpay.errors.RazorpayError as e:
                current_app.logger.error(f"Razorpay verification failed: {str(e)}")
                return jsonify({"message": "Payment verification failed", "error": str(e)}), 400

        # Create an access code for this batch
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        confirmed_ids  = []
        pass_type_name = None
        pass_used_id   = None
        user_id        = None

        for booking_id in booking_ids:
            booking = Booking.query.filter_by(id=booking_id).first()
            if not booking or booking.status == 'confirmed':
                continue

            if user_id is None:
                user_id = booking.user_id

            available_game = AvailableGame.query.filter_by(id=booking.game_id).first()
            vendor         = Vendor.query.filter_by(id=available_game.vendor_id).first() if available_game else None
            slot_obj       = Slot.query.filter_by(id=booking.slot_id).first()
            user           = User.query.filter_by(id=booking.user_id).first()

            if not all([available_game, vendor, slot_obj, user]):
                current_app.logger.warning(f"Booking {booking_id} missing related data")
                continue

            # Pass logic
            active_pass = None
            if use_pass:
                active_pass = UserPass.query.filter_by(
                    id=user_pass_id,
                    user_id=user.id,
                    is_active=True
                ).first()
                if not active_pass or active_pass.valid_to < book_date:
                    return jsonify({"message": "Invalid or expired pass"}), 400
                pass_used_id   = active_pass.id
                pass_type_name = active_pass.cafe_pass.pass_type.name if active_pass.cafe_pass.pass_type else None

            # Calculate slot + extras
            slot_price   = available_game.single_slot_price
            extras_total = 0
            for extra in extra_services_list:
                menu_obj = ExtraServiceMenu.query.filter_by(id=extra.get('item_id'), is_active=True).first()
                if not menu_obj:
                    continue
                extras_total += menu_obj.price * extra.get('quantity', 1)

            # Voucher discount
            voucher             = None
            discount_percentage = 0
            if voucher_code:
                voucher = Voucher.query.filter_by(code=voucher_code, user_id=user.id, is_active=True).first()
                if voucher:
                    discount_percentage = voucher.discount_percentage
                else:
                    return jsonify({'message': 'Invalid or expired voucher'}), 400

            # Amount calculation
            if active_pass:
                discount_amount = slot_price
                amount_payable  = extras_total
            else:
                total_before_discount = slot_price + extras_total
                discount_amount       = int(total_before_discount * discount_percentage / 100)
                amount_payable        = total_before_discount - discount_amount
                pass_used_id          = None
                pass_type_name        = None

            # Payment processing
            if payment_mode == "wallet":
                BookingService.debit_wallet(user.id, booking.id, amount_payable)
                payment_mode_used         = "wallet"
                razorpay_payment_verified = True
            else:
                if amount_payable == 0:
                    razorpay_payment_verified = True
                elif not razorpay_payment_verified:
                    return jsonify({"message": "Payment not verified"}), 400
                payment_mode_used = "payment_gateway"

            # Confirm booking
            booking.status         = 'confirmed'
            booking.updated_at     = datetime.utcnow()
            booking.access_code_id = access_code_entry.id

            # Transaction record (consider adding a nullable pass_id to Transaction for traceability)
            transaction = Transaction(
                booking_id       = booking.id,
                vendor_id        = vendor.id,
                user_id          = user.id,
                user_name        = user.name,
                original_amount  = slot_price + extras_total,
                discounted_amount= discount_amount,
                amount           = amount_payable,
                mode_of_payment  = payment_mode_used,
                booking_date     = datetime.utcnow().date(),
                booked_date      = book_date,
                booking_time     = datetime.utcnow().time(),
                reference_id     = payment_id if payment_mode_used == "payment_gateway" else None
            )
            db.session.add(transaction)
            db.session.flush()

            if payment_id and payment_mode_used == "payment_gateway":
                BookingService.save_payment_transaction_mapping(booking.id, transaction.id, payment_id)

            # Clear and save extras
            BookingExtraService.query.filter_by(booking_id=booking.id).delete()
            for extra in extra_services_list:
                menu_obj = ExtraServiceMenu.query.filter_by(id=extra.get('item_id'), is_active=True).first()
                if not menu_obj:
                    continue

                quantity = extra.get('quantity', 1)
                unit_price = menu_obj.price
                total_price = unit_price * quantity

                booking_extra = BookingExtraService(
                    booking_id=booking.id,
                    menu_item_id=menu_obj.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                db.session.add(booking_extra)

            # Mark voucher as used
            if voucher:
                voucher.is_active = False
                db.session.add(VoucherRedemptionLog(
                    user_id    = user.id,
                    voucher_id = voucher.id,
                    booking_id = booking.id
                ))

            # Reward Hash Coins
            user_hash_coin = UserHashCoin.query.filter_by(user_id=user.id).first()
            if not user_hash_coin:
                user_hash_coin = UserHashCoin(user_id=user.id, hash_coins=0)
                db.session.add(user_hash_coin)
            user_hash_coin.hash_coins += 1000

            # Vendor analytics
            BookingService.insert_into_vendor_dashboard_table(transaction.id, -1)
            BookingService.insert_into_vendor_promo_table(transaction.id, -1)

            # Send booking confirmation email
            booking_mail(
                gamer_name      = user.name,
                gamer_phone     = user.contact_info.phone,
                gamer_email     = user.contact_info.email,
                cafe_name       = vendor.cafe_name,
                booking_date    = datetime.utcnow().strftime("%Y-%m-%d"),
                booked_for_date = str(book_date),
                booking_details = [{
                    "booking_id": booking.id,
                    "slot_time": f"{slot_obj.start_time} - {slot_obj.end_time}"
                }],
                price_paid      = amount_payable
            )

            confirmed_ids.append(booking.id)

        db.session.commit()
        return jsonify({
            'message': 'Bookings confirmed successfully',
            'confirmed_ids': confirmed_ids,
            'pass_used_id': pass_used_id,
            'pass_type': pass_type_name,
            'amount_paid': amount_payable
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error confirming booking")
        return jsonify({'error': str(e)}), 500

@booking_blueprint.route('/redeem-voucher', methods=['POST'])
@auth_required_self(decrypt_user=True) 
def redeem_voucher():
    user_id = g.auth_user_id 
    data = request.json
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
    import string
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

@booking_blueprint.route('/users/bookings', methods=['GET'])
@auth_required_self(decrypt_user=True) 
def get_user_bookings():
    user_id = g.auth_user_id 
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
    Handles waive-off and extra controller fare.
    """
    try:
        current_app.logger.info("New Booking Triggered")
        data = request.json

        console_type = data.get("consoleType")
        name = data.get("name")
        email = data.get("email")
        phone = data.get("phone")
        booked_date = data.get("bookedDate")
        slot_ids = data.get("slotId")
        payment_type = data.get("paymentType")
        console_id = data.get("consoleId")
        is_rapid_booking = data.get("isRapidBooking")
        booking_type = data.get("bookingType") or "direct"
        user_id = data.get("userId")
        waive_off_total = float(data.get("waiveOffAmount", 0.0))
        extra_controller_fare = float(data.get("extraControllerFare", 0.0))

        dashboard_status = None

        if not all([name, phone, booked_date, slot_ids, payment_type]):
            return jsonify({"message": "Missing required fields"}), 400

        user = (
            db.session.query(User).filter(User.id == user_id).first()
            if user_id
            else db.session.query(User).join(ContactInfo).filter(ContactInfo.email == email).first()
        )

        if not user:
            user = User(
                fid=generate_fid(),
                avatar_path="Not defined",
                name=name,
                game_username = name.lower().replace(" ", "_") + str(random.randint(1000, 9999)),
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

        available_game = db.session.query(AvailableGame).filter_by(vendor_id=vendor_id).first()
        if not available_game:
            return jsonify({"message": "Game not found for this vendor"}), 404

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

        if len(slot_entries) != len(slot_ids):
            return jsonify({"message": "One or more slots not found or unavailable"}), 400

        for slot in slot_entries:
            if slot[1] <= 0 or not slot[2]:
                return jsonify({"message": f"Slot {slot[0]} is fully booked"}), 400

        bookings = []
        code = generate_access_code()
        access_code_entry = AccessBookingCode(access_code=code)
        db.session.add(access_code_entry)
        db.session.flush()

        for slot_id in slot_ids:
            slot_obj = db.session.query(Slot).filter_by(id=slot_id).first()
            booking = Booking(
                slot_id=slot_id,
                game_id=available_game.id,
                user_id=user.id,
                status="confirmed",
                access_code_id=access_code_entry.id
            )
            db.session.add(booking)
            db.session.flush()
            bookings.append(booking)

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

        db.session.commit()

        # Create transaction entries
        transactions = []
        waive_off_per_slot = waive_off_total / len(bookings) if bookings else 0.0

        for booking in bookings:
            original_amount = available_game.single_slot_price
            discounted_amount = waive_off_per_slot
            final_amount = max(original_amount - discounted_amount, 0.0)

            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor_id,
                user_id=user.id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                original_amount=original_amount,
                discounted_amount=discounted_amount,
                amount=final_amount,
                mode_of_payment=payment_type,
                booking_type=booking_type,
                settlement_status="NA" if payment_type != "paid" else "completed"
            )
            db.session.add(transaction)
            transactions.append(transaction)

        if extra_controller_fare > 0:
            controller_transaction = Transaction(
                booking_id=bookings[0].id,
                vendor_id=vendor_id,
                user_id=user.id,
                booked_date=datetime.strptime(booked_date, "%Y-%m-%d").date(),
                booking_date=datetime.utcnow().date(),
                booking_time=datetime.utcnow().time(),
                user_name=user.name,
                original_amount=extra_controller_fare,
                discounted_amount=0,
                amount=extra_controller_fare,
                mode_of_payment=payment_type,
                booking_type="extra_controller",
                settlement_status="NA" if payment_type != "paid" else "completed"
            )
            db.session.add(controller_transaction)
            transactions.append(controller_transaction)

        if is_rapid_booking:
            dashboard_status = "current"
            console_table = f"VENDOR_{vendor_id}_CONSOLE_AVAILABILITY"
            db.session.execute(
                text(f"""
                    UPDATE {console_table}
                    SET is_available = FALSE
                    WHERE console_id = :console_id AND game_id = :game_id
                """),
                {"console_id": console_id, "game_id": available_game.id}
            )

        db.session.commit()

        socketio = current_app.extensions['socketio']
        for booking in bookings:
            socketio.emit('slot_booked', {
                'slot_id': booking.slot_id,
                'booking_id': booking.id,
                'status': 'booked'
            })

        for trans in transactions:
            console_id_val = console_id if console_id is not None else -1
            BookingService.insert_into_vendor_dashboard_table(trans.id, console_id_val, dashboard_status)
            BookingService.insert_into_vendor_promo_table(trans.id, console_id_val)

        booking_details = []
        for booking in bookings:
            slot_obj = db.session.query(Slot).filter_by(id=booking.slot_id).first()
            slot_time = f"{str(slot_obj.start_time)} - {str(slot_obj.end_time)}" if slot_obj else "N/A"
            booking_details.append({
                "booking_id": booking.id,
                "slot_time": slot_time
            })

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
    Records extra booking (time extended) played by the user in a gaming cafe, with waive-off functionality.
    """
    try:
        data = request.json

        required_fields = ["consoleNumber", "consoleType", "date", "slotId", "userId", "username", "amount", "gameId", "modeOfPayment", "vendorId"]
        if not all(data.get(field) is not None for field in required_fields):
            return jsonify({"message": "Missing required fields"}), 400

        # Extract values
        console_number = data["consoleNumber"]
        console_type = data["consoleType"]
        booked_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        slot_id = data["slotId"]
        user_id = data["userId"]
        username = data["username"]
        amount = float(data["amount"])
        game_id = data["gameId"]
        mode_of_payment = data["modeOfPayment"]
        vendor_id = data["vendorId"]
        waive_off_amount = float(data.get("waiveOffAmount", 0.0))  # Optional waive-off amount

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

        # Calculate final amount after waive-off
        original_amount = amount
        discounted_amount = waive_off_amount
        final_amount = max(original_amount - discounted_amount, 0.0)

        # Create a transaction for extra booking
        transaction = Transaction(
            booking_id=extra_booking.id,
            vendor_id=vendor_id,
            user_id=user_id,
            booked_date=booked_date,
            booking_time=datetime.utcnow().time(),
            user_name=username,
            original_amount=original_amount,
            discounted_amount=discounted_amount,
            amount=final_amount,
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

        # Send the extra booking email
        extra_booking_time_mail(
            username=username,
            user_email=gamer_email,
            booked_date=booked_date.strftime("%Y-%m-%d"),
            slot_time=slot_time_str,
            console_type=console_type,
            console_number=console_number,
            amount=final_amount,  # Use final_amount after waive-off
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
    
@booking_blueprint.route('/jobs/render/create', methods=['POST'])
def create_render_one_off_job():
    """
    Create a one-off job in Render dashboard
    """
    try:
        api_key = os.getenv('RENDER_API_KEY' , 'rnd_bJpw79wtDkiZSy2DqD2AybGPjj5T')
        service_id = os.getenv('SERVICE_ID', 'srv-culflkl6l47c73dntal0')
        
        url = f"https://api.render.com/v1/services/{service_id}/jobs"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
        'startCommand': "PYTHONPATH=/app python -m app.jobs.release_slot"
        }
    
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 201:
            job_data = response.json()
            return jsonify({
                "message": "One-off job created successfully",
                "job_id": job_data.get('id'),
                "service_id": job_data.get('serviceId'),
                "start_command": job_data.get('startCommand')
            }), 201
        else:
            return jsonify({
                "error": "Failed to create one-off job",
                "details": response.text
            }), response.status_code
            
    except Exception as e:
        return jsonify({
            "error": "Failed to create one-off job",
            "details": str(e)
        }), 500

def now_utc():
    return datetime.now(timezone.utc)

def to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Defensive: treat naive as IST, then to UTC
        return IST.localize(dt).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)

@booking_blueprint.route("/release_slot_job", methods=["POST"])
def release_slot_controller():
    """
    Releases bookings stuck in 'pending_verified' that are older than 2 minutes.
    Uses Booking.created_at (IST-aware) and converts to UTC for comparison.
    """
    now = now_utc()
    two_minutes_ago_utc = now - timedelta(minutes=2)
    now_ist = now.astimezone(IST)
    two_minutes_ago_ist = two_minutes_ago_utc.astimezone(IST)

    # Optional: constrain to a recent window to keep scans lean
    # Set to None to disable.
    recent_window_hours = 6
    lower_bound_utc = now - timedelta(hours=recent_window_hours) if recent_window_hours else None
    lower_bound_ist = lower_bound_utc.astimezone(IST) if lower_bound_utc else None

    current_app.logger.info(
        "🔍 Start release scan | now_utc=%s | now_ist=%s | threshold_utc=%s | threshold_ist=%s | recent_window_hours=%s | lower_bound_utc=%s | lower_bound_ist=%s",
        now.isoformat(), now_ist.isoformat(),
        two_minutes_ago_utc.isoformat(), two_minutes_ago_ist.isoformat(),
        recent_window_hours, (lower_bound_utc.isoformat() if lower_bound_utc else None),
        (lower_bound_ist.isoformat() if lower_bound_ist else None),
    )

    try:
        # Quick metrics before fetching
        total_pending = db.session.query(func.count(Booking.id)).filter(Booking.status == 'pending_verified').scalar()
        current_app.logger.info("📊 Metrics: total_pending_verified=%s", total_pending)

        # Build base query
        q = (
            db.session.query(Booking)
            .options(
                joinedload(Booking.slot),
                joinedload(Booking.game)
            )
            .filter(Booking.status == 'pending_verified')
        )

        # Upper bound (safety) — created_at should not be in the future relative to now_ist
        q = q.filter(Booking.created_at <= now_ist)

        # Lower bound for performance if enabled
        if lower_bound_ist:
            q = q.filter(Booking.created_at >= lower_bound_ist)

        # Fetch candidates
        candidates = q.all()

        # Log candidate summary
        if candidates:
            min_created = min(b.created_at for b in candidates if b.created_at is not None)
            max_created = max(b.created_at for b in candidates if b.created_at is not None)
            current_app.logger.info(
                "📦 Candidates fetched: count=%s | created_at_min_ist=%s | created_at_max_ist=%s",
                len(candidates),
                (min_created.astimezone(IST).isoformat() if min_created else None),
                (max_created.astimezone(IST).isoformat() if max_created else None),
            )
        else:
            current_app.logger.info("📦 Candidates fetched: count=0 (no pending_verified within time window)")

        released = 0
        skipped = 0
        errors = []

        for booking in candidates:
            try:
                created_ist = booking.created_at  # should be tz-aware IST by model default
                created_utc = to_utc(created_ist)

                current_app.logger.debug(
                    "🔎 Candidate booking_id=%s user_id=%s status=%s created_ist=%s created_utc=%s",
                    booking.id, booking.user_id, booking.status,
                    (created_ist.isoformat() if created_ist else None),
                    (created_utc.isoformat() if created_utc else None),
                )

                if created_utc is None:
                    skipped += 1
                    current_app.logger.warning(
                        "⛔ Skip booking_id=%s: created_at is None or invalid", booking.id
                    )
                    continue

                # Decision: older than 2 minutes?
                if created_utc > two_minutes_ago_utc:
                    skipped += 1
                    current_app.logger.debug(
                        "⏭️ Skip booking_id=%s: age too young (created_utc=%s > threshold_utc=%s)",
                        booking.id, created_utc.isoformat(), two_minutes_ago_utc.isoformat()
                    )
                    continue

                # Format as YYYY-MM-DD (UTC)
                date_for_release_str = created_utc.strftime("%Y-%m-%d")
                vendor_id = getattr(booking.game, "vendor_id", None) if booking.game else None
                current_app.logger.info(
                    "⏳ Releasing id=%s user_id=%s slot_id=%s vendor_id=%s date_for_release=%s (UTC)",
                    booking.id, booking.user_id, booking.slot_id, vendor_id, date_for_release_str
                )

                # Perform release
                # If your release signature differs, adjust here.
                booked_date = getattr(booking, "booked_date", date_for_release_str)  # may not exist; log it for clarity
                current_app.logger.debug(
                    "🔧 Calling Booking.release_slot(slot_id=%s, booking_id=%s, booked_date=%s)",
                    booking.slot_id, booking.id, booked_date
                )
                BookingService.release_slot(booking.slot_id, booking.id, booked_date)

                released += 1
                current_app.logger.info("✅ Released booking_id=%s", booking.id)

            except Exception as item_err:
                db.session.rollback()
                errors.append({"booking_id": booking.id, "error": str(item_err)})
                current_app.logger.exception("❌ Release failed for booking_id=%s: %s", booking.id, item_err)

        # Clean up session after loop
        db.session.remove()

        current_app.logger.info(
            "🧾 Release summary | found=%s | released=%s | skipped=%s | errors=%s",
            len(candidates), released, skipped, len(errors)
        )

        status_code = 200 if not errors else 207
        return jsonify({
            "message": "Release scan complete",
            "found": len(candidates),
            "released": released,
            "skipped": skipped,
            "errors": errors
        }), status_code

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("❌ Release scan failed: %s", e)
        return jsonify({"message": "Release scan failed", "error": str(e)}), 500
    finally:
        db.session.remove()
