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
    def create_booking(
        slot_id: int, 
        game_id: int, 
        user_id: int, 
        socketio, 
        book_date, 
        is_pay_at_cafe: bool = False,
        booking_mode: str = 'regular'  # ✅ NEW PARAMETER
    ):
        """
        Create a booking with specified mode.

        Args:
            booking_mode: 'regular' or 'private' - for tracking/display purposes
                          Both modes follow same slot availability and payment rules
        """
        cid = getattr(g, "cid", None) or str(uuid.uuid4())
        log = current_app.logger

        log.info(
            "create_booking.start cid=%s slot_id=%s game_id=%s user_id=%s book_date=%s "
            "is_pay_at_cafe=%s booking_mode=%s",
            cid, slot_id, game_id, user_id, book_date, is_pay_at_cafe, booking_mode
        )

        # ✅ Validate booking_mode
        if booking_mode not in ['regular', 'private']:
            log.warning(f"Invalid booking_mode '{booking_mode}', defaulting to 'regular'")
            booking_mode = 'regular'

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
        slot_price = ag_row[1]
        game_name = ag_row[2]

        log.info(
            "create_booking.meta_parsed cid=%s vendor_id=%s slot_price=%s game_name=%s mode=%s",
            cid, vendor_id, slot_price, game_name, booking_mode
        )

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

        # STEP 4: Create booking with booking_mode
        try:
            booking = Booking(
                slot_id=slot_id,
                game_id=game_id,
                user_id=user_id,
                booking_mode=booking_mode,  # ✅ SET THE MODE HERE
                status="pending_acceptance" if is_pay_at_cafe else "pending_verified",
                created_at=datetime.utcnow()
            )
            db.session.add(booking)
            db.session.flush()
            bid = booking.id
            log.info(
                "create_booking.booking_created cid=%s bid=%s mode=%s status=%s", 
                cid, bid, booking_mode, booking.status
            )
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
            log.info("create_booking.db_committed cid=%s bid=%s mode=%s", cid, bid, booking_mode)
        except Exception as e:
            db.session.rollback()
            log.exception("create_booking.db_commit_failed cid=%s bid=%s error=%s", cid, bid, e)
            raise

        # STEP 7: Emit event (non-fatal) with booking_mode
        try:
            machine_status = "pending_acceptance" if is_pay_at_cafe else "pending_verified"
            log.info("create_booking.emit_prepare cid=%s bid=%s status=%s mode=%s", 
                     cid, bid, machine_status, booking_mode)

            event_data = {
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
                "booking_mode": booking_mode,  # ✅ ADD MODE TO EVENT
                "cid": cid,
            }

            # Emit to vendor room
            emit_booking_event(
                socketio,
                event="booking",
                data=event_data,
                vendor_id=vendor_id
            )

            # Emit to admin dashboard
            emit_booking_event(
                socketio,
                event="booking",
                data=event_data,
                room="dashboard_admin"
            )

            log.info("create_booking.emit_done cid=%s bid=%s mode=%s", cid, bid, booking_mode)
        except Exception as e:
            log.exception("create_booking.emit_failed cid=%s bid=%s error=%s", cid, bid, e)

        log.info("create_booking.success cid=%s bid=%s mode=%s", cid, bid, booking_mode)
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

                if booking and booking.status in ["pending_verified", "cancelled"]:
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
        if status != None and status == "current":
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
            "book_status": book_status
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

    @staticmethod
    def create_private_booking(
        vendor_id: int,
        user_info: dict,
        game_id: int,
        booking_date,
        start_time,
        end_time,
        duration_hours,
        hourly_rate,
        extra_services: list = None,
        payment_mode: str = 'Cash',
        manual_discount = 0,
        waive_off_amount = 0,
        notes: str = None,
        socketio=None
    ):
        """
        Create a private booking without slot availability checks.

        Args:
            vendor_id: Vendor ID
            user_info: Dict with user details (name, email, phone, user_id optional)
            game_id: Available game ID
            booking_date: Date for booking
            start_time: Custom start time
            end_time: Custom end time
            duration_hours: Duration in hours
            hourly_rate: Price per hour
            extra_services: List of extra services [{item_id, quantity}]
            payment_mode: Cash/UPI/Pass
            manual_discount: Manual discount amount
            waive_off_amount: Amount to waive off
            notes: Optional notes
            socketio: SocketIO instance

        Returns:
            Booking object
        """
        from decimal import Decimal

        cid = getattr(g, "cid", None) or str(uuid.uuid4())
        log = current_app.logger

        log.info(
            f"create_private_booking.start cid={cid} vendor_id={vendor_id} "
            f"game_id={game_id} date={booking_date} duration={duration_hours}hrs"
        )

        try:
            # STEP 1: Get or create user
            user_id = user_info.get('user_id')

            if not user_id:
                # Check if user exists by email
                from models.contactInfo import ContactInfo
                from models.vendor import Vendor

                contact = ContactInfo.query.filter_by(
                    email=user_info['email'],
                    parent_type='user'
                ).first()

                if contact:
                    user = User.query.get(contact.parent_id)
                else:
                    # Create new user
                    user = User(
                        fid=str(uuid.uuid4()),
                        name=user_info['name'],
                        game_username=user_info['email'].split('@')[0],
                        parent_type='user'
                    )
                    db.session.add(user)
                    db.session.flush()

                    # Create contact info
                    contact = ContactInfo(
                        email=user_info['email'],
                        phone=user_info['phone'],
                        parent_id=user.id,
                        parent_type='user'
                    )
                    db.session.add(contact)
                    db.session.flush()

                user_id = user.id
            else:
                user = User.query.get(user_id)
                if not user:
                    raise ValueError(f"User {user_id} not found")

            log.info(f"create_private_booking.user_resolved cid={cid} user_id={user_id}")

            # STEP 2: Validate game and vendor
            available_game = AvailableGame.query.get(game_id)
            if not available_game:
                raise ValueError(f"Game {game_id} not found")

            if available_game.vendor_id != vendor_id:
                raise ValueError("Game does not belong to this vendor")

            from models.vendor import Vendor
            vendor = Vendor.query.get(vendor_id)
            if not vendor:
                raise ValueError(f"Vendor {vendor_id} not found")

            log.info(
                f"create_private_booking.game_validated cid={cid} "
                f"game={available_game.game_name} vendor={vendor.cafe_name}"
            )

            # STEP 3: Calculate amounts
            slot_cost = Decimal(str(hourly_rate)) * Decimal(str(duration_hours))

            # Calculate extras
            extras_total = Decimal('0')
            if extra_services:
                for extra in extra_services:
                    menu_item = ExtraServiceMenu.query.get(extra['item_id'])
                    if menu_item and menu_item.is_active:
                        extras_total += Decimal(str(menu_item.price)) * extra['quantity']

            # Total calculations
            original_amount = slot_cost + extras_total
            discount_amount = Decimal(str(manual_discount)) + Decimal(str(waive_off_amount))
            total_amount = original_amount - discount_amount

            log.info(
                f"create_private_booking.amounts_calculated cid={cid} "
                f"original={original_amount} discount={discount_amount} total={total_amount}"
            )

            # STEP 4: Create private booking
            booking = Booking(
                user_id=user_id,
                game_id=game_id,
                booking_mode='private',  # ✅ Mark as private
                slot_id=None,  # ✅ No slot for private bookings
                custom_start_time=start_time,
                custom_end_time=end_time,
                duration_hours=duration_hours,
                status='confirmed',  # ✅ Directly confirmed
                created_at=datetime.utcnow()
            )
            db.session.add(booking)
            db.session.flush()

            log.info(f"create_private_booking.booking_created cid={cid} booking_id={booking.id}")

            # STEP 5: Create transaction
            transaction = Transaction(
                booking_id=booking.id,
                vendor_id=vendor_id,
                user_id=user_id,
                user_name=user.name,
                original_amount=float(original_amount),
                discounted_amount=float(discount_amount),
                amount=float(total_amount),
                mode_of_payment=payment_mode,
                booking_type='private_booking',  # ✅ Special booking type
                booking_date=datetime.utcnow().date(),
                booked_date=booking_date,
                booking_time=datetime.utcnow().time(),
                reference_id=notes  # Store notes in reference_id
            )
            db.session.add(transaction)
            db.session.flush()

            log.info(f"create_private_booking.transaction_created cid={cid} trans_id={transaction.id}")

            # STEP 6: Add extra services
            if extra_services:
                for extra in extra_services:
                    menu_item = ExtraServiceMenu.query.get(extra['item_id'])
                    if not menu_item or not menu_item.is_active:
                        continue

                    booking_extra = BookingExtraService(
                        booking_id=booking.id,
                        menu_item_id=menu_item.id,
                        quantity=extra['quantity'],
                        unit_price=menu_item.price,
                        total_price=menu_item.price * extra['quantity']
                    )
                    db.session.add(booking_extra)

            # STEP 7: Insert into vendor dashboard (special handling for private)
            BookingService.insert_into_vendor_dashboard_table_private(
                trans_id=transaction.id,
                console_id=-1,  # No console assigned yet
                custom_start=start_time,
                custom_end=end_time
            )

            # STEP 8: Insert promo table
            BookingService.insert_into_vendor_promo_table(transaction.id, -1)

            # STEP 9: Commit
            db.session.commit()

            log.info(f"create_private_booking.db_committed cid={cid} booking_id={booking.id}")

            # STEP 10: Emit WebSocket event
            if socketio:
                try:
                    emit_booking_event(
                        socketio,
                        event="private_booking",
                        data={
                            "vendor_id": vendor_id,
                            "booking_id": booking.id,
                            "user_id": user_id,
                            "username": user.name,
                            "game_id": game_id,
                            "game_name": available_game.game_name,
                            "date": str(booking_date),
                            "start_time": str(start_time),
                            "end_time": str(end_time),
                            "duration_hours": float(duration_hours),
                            "total_amount": float(total_amount),
                            "payment_mode": payment_mode,
                            "booking_mode": "private",
                            "booking_status": "confirmed",
                            "status": "confirmed",
                            "cid": cid
                        },
                        vendor_id=vendor_id
                    )

                    # Also emit to admin dashboard
                    socketio.emit("private_booking", {
                        "vendor_id": vendor_id,
                        "booking_id": booking.id,
                        "user_id": user_id,
                        "username": user.name,
                        "game_name": available_game.game_name,
                        "date": str(booking_date),
                        "time_range": f"{start_time} - {end_time}",
                        "duration": float(duration_hours),
                        "amount": float(total_amount)
                    }, to="dashboard_admin")

                    log.info(f"create_private_booking.websocket_emitted cid={cid}")
                except Exception as e:
                    log.exception(f"create_private_booking.websocket_failed cid={cid} error={e}")

            log.info(f"create_private_booking.success cid={cid} booking_id={booking.id}")

            return booking

        except Exception as e:
            db.session.rollback()
            log.exception(f"create_private_booking.failed cid={cid} error={e}")
            raise

    @staticmethod
    def insert_into_vendor_dashboard_table_private(trans_id, console_id, custom_start, custom_end):
        """
        Special insertion for private bookings with custom times.
        Modified to handle private bookings without slot_id.
        """

        trans_obj = Transaction.query.filter_by(id=trans_id).first()
        if not trans_obj:
            raise ValueError(f"Transaction with ID {trans_id} not found.")

        user_obj = User.query.filter_by(id=trans_obj.user_id).first()
        book_obj = Booking.query.filter_by(id=trans_obj.booking_id).first()
        available_game_obj = AvailableGame.query.filter_by(id=book_obj.game_id).first()

        # ✅ For private bookings, use custom times instead of slot times
        start_time = custom_start
        end_time = custom_end

        vendor_id = trans_obj.vendor_id
        table_name = f"VENDOR_{vendor_id}_DASHBOARD"

        sql_insert = text(f"""
            INSERT INTO {table_name} 
            (username, user_id, start_time, end_time, date, book_id, game_id, game_name, console_id, book_status)
            VALUES (:username, :user_id, :start_time, :end_time, :date, :book_id, :game_id, :game_name, :console_id, :book_status)
        """)

        db.session.execute(sql_insert, {
            "username": user_obj.name,
            "user_id": user_obj.id,
            "start_time": start_time,
            "end_time": end_time,
            "date": trans_obj.booked_date,
            "book_id": trans_obj.booking_id,
            "game_id": book_obj.game_id,
            "game_name": available_game_obj.game_name,
            "console_id": console_id,
            "book_status": "private"  # ✅ Special status for private bookings
        })

        db.session.commit()
        current_app.logger.info(f"Inserted private booking {trans_id} into {table_name}")
