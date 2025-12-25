from models.booking import Booking, db
from models.availableGame import AvailableGame
from flask_socketio import socketio
from models.slot import Slot
from models.booking import Booking
from db.extensions import db
from datetime import datetime
from models.transaction import Transaction
from models.user import User
from models.paymentTransactionMapping import PaymentTransactionMapping
from models.hashWallet import HashWallet
from models.hashWalletTransaction import HashWalletTransaction
from models.passModels import UserPass
from sqlalchemy.orm import joinedload
from models.bookingExtraService import BookingExtraService
from models.extraServiceMenuImage import ExtraServiceMenuImage
from models.passModels import CafePass
from models.extraServiceMenu import ExtraServiceMenu
from sqlalchemy import or_
from utils.realtime import emit_booking_event
from flask import current_app, g
from sqlalchemy import text
import uuid


class BookingService:
    socketio = None  # Placeholder for the socketio instance

    @staticmethod
    def set_socketio(socketio_instance):
        BookingService.socketio = socketio_instance  # Set the socketio instance

    @staticmethod
    def get_user_bookings(user_id):
        return db.session.query(Booking)\
        .options(
            joinedload(Booking.slot),
            joinedload(Booking.transaction),
            joinedload(Booking.access_code_entry),
            joinedload(Booking.booking_extra_services)
                .joinedload(BookingExtraService.extra_service_menu)  # Note: using menu_item, not extra_service_menu
                .joinedload(ExtraServiceMenu.images)
        )\
        .filter(Booking.user_id == user_id)\
        .all()

    # @staticmethod
    # def get_user_bookings(user_id):
    #     return Booking.query.filter_by(user_id=user_id).all()

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

    # @staticmethod
    # def create_booking_old(slot_id, game_id, user_id, socketio, book_date):
    #     # ✅ Get vendor_id from available_games
    #     available_game = db.session.execute(
    #         text("SELECT vendor_id FROM available_games WHERE id = (SELECT gaming_type_id FROM slots WHERE id = :slot_id)"),
    #         {"slot_id": slot_id}
    #     ).fetchone()

    #     if not available_game:
    #         raise ValueError("Vendor not found for this slot.")

    #     vendor_id = available_game[0]

    #     current_app.logger.info(f"Test1 {vendor_id} . {slot_id}, {book_date}")

    #     # ✅ Check availability in the VENDOR_{vendor_id}_SLOT table
    #     slot_entry = db.session.execute(
    #         text(f"""
    #             SELECT * FROM VENDOR_{vendor_id}_SLOT
    #             WHERE slot_id = :slot_id AND date = :book_date
    #         """),
    #         {"slot_id": slot_id, "book_date": book_date}
    #     ).fetchone()

    #     current_app.logger.info(f"Test {slot_entry} .")

    #     if not slot_entry or slot_entry[0] <= 0:
    #         raise ValueError("Slot is fully booked for this date.")

    #     try:
    #         # ✅ Decrease `available_slot` by 1 in the table
    #         update_query = text(f"""
    #             UPDATE VENDOR_{vendor_id}_SLOT
    #             SET available_slot = available_slot - 1,
    #                 is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
    #             WHERE slot_id = :slot_id
    #             AND date = :book_date;
    #         """)
    #         db.session.execute(update_query, {"slot_id": slot_id, "book_date": book_date})
    #         db.session.commit()

    #         # ✅ Create booking
    #         booking = Booking(slot_id=slot_id, game_id=game_id, user_id=user_id, status='pending_verified')
    #         db.session.add(booking)
    #         db.session.commit()

    #         socketio.emit('slot_pending', {'slot_id': slot_id, 'booking': booking.id, 'status': 'pending'})

    #         if socketio:
    #             socketio.emit(
    #                 "booking_updated",
    #                 {
    #                     "booking_id": booking.id,
    #                     "slot_id": slot_id,
    #                     "status": "pending_verified"
    #                 },
    #                 room=f"vendor_{vendor_id}"
    #             )

    #         return booking

    #     except Exception as e:
    #         db.session.rollback()
    #         raise ValueError(f"Failed to create booking: {str(e)}")

    @staticmethod
    def create_booking(slot_id: int, game_id: int, user_id: int, socketio, book_date, is_pay_at_cafe: bool = False):
        cid = getattr(g, "cid", None) or str(uuid.uuid4())
        log = current_app.logger

        log.info("create_booking.start cid=%s slot_id=%s game_id=%s user_id=%s book_date=%s is_pay_at_cafe=%s",
                 cid, slot_id, game_id, user_id, book_date, is_pay_at_cafe)

        # STEP 1: Resolve vendor and game meta (BUGFIX: proper unpack)
        try:
            ag_row = db.session.execute(
                text("""
                    SELECT ag.vendor_id, ag.single_slot_price, ag.game_name
                    FROM available_games ag
                    JOIN slots s ON s.gaming_type_id = ag.id
                    WHERE s.id = :slot_id
                """),
                {"slot_id": slot_id}
            ).fetchone()
            log.info("create_booking.meta_loaded cid=%s has_ag_row=%s", cid, bool(ag_row))
        except Exception as e:
            log.exception("create_booking.meta_query_failed cid=%s slot_id=%s error=%s", cid, slot_id, e)
            raise

        if not ag_row:
            log.warning("create_booking.no_vendor_for_slot cid=%s slot_id=%s", cid, slot_id)
            raise ValueError("Vendor not found for this slot.")

        # Properly unpack the tuple
        vendor_id = ag_row[0]
        slot_price = ag_row
        game_name = ag_row

        log.info("create_booking.meta_parsed cid=%s vendor_id=%s slot_price=%s game_name=%s",
                 cid, vendor_id, slot_price, game_name)

        # STEP 2A: Lock and read vendor availability row (match schema)
        try:
            vendor_slot_row = db.session.execute(
                text(f"""
                    SELECT available_slot, date
                    FROM VENDOR_{vendor_id}_SLOT
                    WHERE slot_id = :slot_id AND date = :book_date
                    FOR UPDATE
                """),
                {"slot_id": slot_id, "book_date": book_date}
            ).fetchone()
            log.info("create_booking.vendor_slot_locked cid=%s has_row=%s", cid, bool(vendor_slot_row))
        except Exception as e:
            log.exception("create_booking.vendor_slot_query_failed cid=%s vendor_id=%s slot_id=%s error=%s",
                          cid, vendor_id, slot_id, e)
            raise

        if not vendor_slot_row:
            log.warning("create_booking.vendor_slot_missing cid=%s vendor_id=%s slot_id=%s book_date=%s",
                        cid, vendor_id, slot_id, book_date)
            raise ValueError("Slot row not found for this date.")

        available_slot, date_value = vendor_slot_row
        log.info("create_booking.vendor_slot_state cid=%s available_slot=%s date=%s",
                 cid, available_slot, date_value)

        if available_slot is None or available_slot <= 0:
            log.warning("create_booking.slot_full cid=%s vendor_id=%s slot_id=%s date=%s",
                        cid, vendor_id, slot_id, date_value)
            raise ValueError("Slot is fully booked for this date.")

        # STEP 2B: Fetch time/console metadata from slots table
        try:
            slot_meta = db.session.execute(
                text("""
                    SELECT start_time, end_time, -1 AS console_id
                    FROM slots
                    WHERE id = :slot_id
                """),
                {"slot_id": slot_id}
            ).fetchone()
            log.info("create_booking.slot_meta_loaded cid=%s has_meta=%s", cid, bool(slot_meta))
        except Exception as e:
            log.exception("create_booking.slot_meta_query_failed cid=%s slot_id=%s error=%s", cid, slot_id, e)
            raise

        if not slot_meta:
            log.warning("create_booking.slot_meta_missing cid=%s slot_id=%s", cid, slot_id)
            raise ValueError("Slot metadata missing.")

        start_time, end_time, console_id = slot_meta
        log.info("create_booking.slot_meta cid=%s start=%s end=%s console_id=%s",
                 cid, start_time, end_time, console_id)

        # STEP 3: Atomic decrement on vendor slot row
        try:
            update_res = db.session.execute(
                text(f"""
                    UPDATE VENDOR_{vendor_id}_SLOT
                    SET available_slot = available_slot - 1,
                        is_available = CASE WHEN available_slot - 1 = 0 THEN FALSE ELSE is_available END
                    WHERE slot_id = :slot_id AND date = :book_date AND available_slot > 0
                    RETURNING available_slot
                """),
                {"slot_id": slot_id, "book_date": book_date}
            ).fetchone()
            log.info("create_booking.vendor_slot_decrement cid=%s success=%s new_available_slot=%s",
                     cid, bool(update_res), (update_res[0] if update_res else None))
        except Exception as e:
            log.exception("create_booking.vendor_slot_decrement_failed cid=%s vendor_id=%s slot_id=%s error=%s",
                          cid, vendor_id, slot_id, e)
            db.session.rollback()
            raise

        if not update_res:
            db.session.rollback()
            log.warning("create_booking.concurrent_conflict cid=%s vendor_id=%s slot_id=%s date=%s",
                        cid, vendor_id, slot_id, date_value)
            raise ValueError("Concurrent booking conflict. Please retry.")

        # STEP 4: Create booking
        try:
            booking = Booking(
                slot_id=slot_id,
                game_id=game_id,
                user_id=user_id,
                status="pending_acceptance" if is_pay_at_cafe else "pending_verified",
                created_at=datetime.utcnow()
            )
            db.session.add(booking)
            db.session.flush()
            bid = booking.id
            log.info("create_booking.booking_created cid=%s bid=%s", cid, bid)
        except Exception as e:
            db.session.rollback()
            log.exception("create_booking.booking_persist_failed cid=%s vendor_id=%s slot_id=%s error=%s",
                          cid, vendor_id, slot_id, e)
            raise

        # STEP 5: Resolve username (non-fatal)
        try:
            user_row = db.session.execute(
                text("SELECT name FROM users WHERE id = :uid"),
                {"uid": user_id}
            ).fetchone()
            username = user_row[0] if user_row else None
            log.info("create_booking.user_loaded cid=%s user_id=%s has_username=%s",
                     cid, user_id, bool(username))
        except Exception as e:
            username = None
            log.exception("create_booking.user_query_failed cid=%s user_id=%s error=%s", cid, user_id, e)

        # STEP 6: Commit DB
        try:
            db.session.commit()
            log.info("create_booking.db_committed cid=%s bid=%s", cid, bid)
        except Exception as e:
            db.session.rollback()
            log.exception("create_booking.db_commit_failed cid=%s bid=%s error=%s", cid, bid, e)
            raise

        # STEP 7: Emit event (non-fatal)
        try:
            machine_status = "pending_acceptance" if is_pay_at_cafe else "pending_verified"
            log.info("create_booking.emit_prepare cid=%s bid=%s status=%s", cid, bid, machine_status)

            emit_booking_event(
                socketio,
                event="booking",
                data={
                    "vendor_id": vendor_id,
                    "booking_id": bid,
                    "slot_id": slot_id,
                    "user_id": user_id,
                    "username": username,
                    "game_id": game_id,
                    "game": game_name,
                    "consoleType": f"Console-{console_id}" if console_id is not None else None,
                    "consoleNumber": str(console_id) if console_id is not None else None,
                    "date": date_value,
                    "slot_price": slot_price,
                    "time": [{"start_time": start_time, "end_time": end_time}],
                    "processed_time": [{"start_time": start_time, "end_time": end_time}],
                    "status": machine_status,
                    "booking_status": "pending_acceptance" if is_pay_at_cafe else "pending_verified",
                    "cid": cid,
                },
                vendor_id=vendor_id
            )

            emit_booking_event(
                socketio,
                event="booking",
                data={
                    "vendor_id": vendor_id,
                    "booking_id": bid,
                    "slot_id": slot_id,
                    "user_id": user_id,
                    "username": username,
                    "game_id": game_id,
                    "game": game_name,
                    "consoleType": f"Console-{console_id}" if console_id is not None else None,
                    "consoleNumber": str(console_id) if console_id is not None else None,
                    "date": date_value,
                    "slot_price": slot_price,
                    "time": [{"start_time": start_time, "end_time": end_time}],
                    "processed_time": [{"start_time": start_time, "end_time": end_time}],
                    "status": machine_status,
                    "booking_status": "pending_acceptance" if is_pay_at_cafe else "pending_verified",
                    "cid": cid,
                },
                room="dashboard_admin"
            )
            log.info("create_booking.emit_done cid=%s bid=%s", cid, bid)
        except Exception as e:
            log.exception("create_booking.emit_failed cid=%s bid=%s error=%s", cid, bid, e)

        log.info("create_booking.success cid=%s bid=%s", cid, bid)
        return booking


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

                if booking and booking.status  in ["pending_verified", "cancelled"]:
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
                    if booking.status == "pending_verified":
                        booking.status = 'verification_failed'
                        db.session.commit()

                    # ✅ Emit WebSocket event to update slot status
                    socketio = current_app.extensions['socketio']
                    socketio.emit('booking', {
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
    def insert_into_vendor_dashboard_table(trans_id, console_id, status=None):
        """Inserts booking and transaction details into the vendor dashboard table."""
        
        # Fetch required objects
        trans_obj = Transaction.query.filter_by(id=trans_id).first()
        if not trans_obj:
            raise ValueError(f"Transaction with ID {trans_id} not found.")

        user_obj = User.query.filter_by(id=trans_obj.user_id).first()
        book_obj = Booking.query.filter_by(id=trans_obj.booking_id).first()
        slot_obj = Slot.query.filter_by(id=book_obj.slot_id).first()
        available_game_obj = AvailableGame.query.filter_by(id=book_obj.game_id).first()
        if status!= None and status == "current":
            book_status = "current"
        elif book_obj.status == "extra":
            book_status = "extra"
        else:
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
        promo_code = "NOPROMO"
        discount_applied = "0"
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

    @staticmethod
    def save_payment_transaction_mapping(booking_id, transaction_id, payment_id):
        if not all([booking_id, transaction_id, payment_id]):
            return  # Skip if any of the values are missing
        
        mapping = PaymentTransactionMapping(
            booking_id=booking_id,
            transaction_id=transaction_id,
            payment_id=payment_id
        )
        db.session.add(mapping)

    @staticmethod
    def debit_wallet(user_id, booking_id, amount):
        wallet = db.session.query(HashWallet).filter_by(user_id=user_id).first()

        if not wallet:
            wallet = HashWallet(user_id=user_id, balance=0)
            db.session.add(wallet)
            db.session.flush()

        if wallet.balance < amount:
            raise ValueError("Insufficient wallet balance")

        wallet.balance -= amount

        wallet_txn = HashWalletTransaction(
            user_id=user_id,
            amount=-amount,
            type='booking',
            reference_id=booking_id
        )
        db.session.add(wallet_txn)

    @staticmethod
    def get_user_pass(user_id, vendor_id, book_date):
        """Return the best valid pass or None."""
        return UserPass.query.join(CafePass).filter(
            UserPass.user_id == user_id,
            UserPass.is_active == True,
            UserPass.valid_to >= book_date,
            CafePass.is_active == True,
            or_(
                CafePass.vendor_id == vendor_id,
                CafePass.vendor_id.is_(None)
            )
        ).order_by(
            CafePass.vendor_id.is_(None).desc()
        ).first()

    @staticmethod
    def get_menu_price(menu_id):
        menu_obj = ExtraServiceMenu.query.filter_by(id=menu_id, is_active=True).first()
        return menu_obj.price if menu_obj else 0
    
