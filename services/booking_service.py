from models.booking import Booking, db
from models.availableGame import AvailableGame

class BookingService:
    @staticmethod
    def create_booking(slot_id, user_id):
        # Generate a unique order number
        order_number = str(uuid.uuid4())

        # Create and persist the booking
        booking = Booking(
            slot_id=slot_id,
            user_id=user_id,
            order_number=order_number,
            is_confirmed=False
        )
        db.session.add(booking)
        db.session.commit()
        return booking

    @staticmethod
    def get_user_bookings(user_id):
        """
        Fetch all bookings for a given user.
        :param user_id: ID of the user
        """
        return Booking.query.filter_by(user_id=user_id).all()

    @staticmethod
    def cancel_booking(booking_id):
        """
        Cancel an existing booking and free up the slot.
        :param booking_id: ID of the booking to be canceled
        """
        booking = Booking.query.get(booking_id)
        if not booking:
            raise ValueError("Booking does not exist.")
        
        # Free up the slot for the game
        game = AvailableGame.query.get(booking.game_id)
        game.total_slot += 1
        db.session.add(game)

        db.session.delete(booking)
        db.session.commit()
        return {"message": "Booking canceled successfully."}

    @staticmethod
    def verifyPayment(payment_id):
        if payment_id == 1234:
            return True
        else:
            return False
