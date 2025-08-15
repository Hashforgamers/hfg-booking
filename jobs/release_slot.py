import logging
import time
from datetime import datetime, timedelta
from sqlalchemy import and_
from app import create_app
from db.extensions import db
from models.transaction import Transaction
from models.booking import Booking
from models.availableGame import AvailableGame
from models.slot import Slot
from models.vendor import Vendor

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def release_unverified_slots():
    """Find unverified bookings older than 2 minutes from transactions in the last 1 hour."""
    logging.info("🔍 Checking for unverified bookings older than 2 minutes...")

    now = datetime.utcnow()
    one_hour_ago = now - timedelta(hours=1)
    two_minutes_ago = now - timedelta(minutes=2)

    try:
        # Query candidate transactions
        candidates = (
            db.session.query(Transaction, Booking)
            .join(Booking, Booking.id == Transaction.booking_id)
            .filter(
                Transaction.booking_type == 'booking',
                Transaction.booking_date == now.date(),
                Transaction.created_at >= one_hour_ago,
                Booking.status == 'pending_verified'
            )
            .all()
        )

        released_count = 0

        for txn, booking in candidates:
            booking_created_at = datetime.combine(
                txn.booking_date, txn.booking_time
            )

            if booking_created_at <= two_minutes_ago:
                # Gather extra log info
                slot_obj = Slot.query.get(booking.slot_id)
                game_obj = AvailableGame.query.get(booking.game_id)
                vendor_obj = Vendor.query.get(game_obj.vendor_id) if game_obj else None

                logging.info(
                    f"⏳ Releasing slot for booking_id={booking.id} | "
                    f"user_id={booking.user_id} | slot_id={booking.slot_id} | "
                    f"vendor_id={vendor_obj.id if vendor_obj else 'N/A'} ({vendor_obj.cafe_name if vendor_obj else 'Unknown'}) | "
                    f"game_id={booking.game_id} ({game_obj.game_name if game_obj else 'Unknown'}) | "
                    f"booked_at={booking_created_at.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"status={booking.status}"
                )

                # Release slot
                Booking.release_slot(booking.slot_id, booking.id, txn.booked_date)
                released_count += 1
            else:
                logging.debug(f"Skipping booking_id={booking.id} - not older than 2 minutes")

        logging.info(f"✅ Released {released_count} unverified booking slots.")

    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ Slot release job failed: {e}")
    finally:
        db.session.remove()


def main_loop():
    """Run every 30 seconds for 30 days."""
    app, _ = create_app()

    with app.app_context():
        duration_days = 30
        end_time = datetime.utcnow() + timedelta(days=duration_days)

        logging.info(f"🚀 Starting slot release job loop for {duration_days} days...")

        while datetime.utcnow() < end_time:
            release_unverified_slots()
            time.sleep(30)

        logging.info(f"🏁 Slot release job finished after {duration_days} days.")


if __name__ == "__main__":
    main_loop()
