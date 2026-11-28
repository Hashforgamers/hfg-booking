"""GET /api/vendor/<vendor_id>/bookings/<booking_id>/details (dashboard, additive)."""
from flask import Blueprint, jsonify

from db.extensions import db
from models.booking import Booking
from models.transaction import Transaction
from services.booking_details import details_payload
from services.vendor_access import require_vendor_permission

booking_details_blueprint = Blueprint("booking_details", __name__)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


@booking_details_blueprint.route("/vendor/<int:vendor_id>/bookings/<int:booking_id>/details", methods=["GET"])
@require_vendor_permission("booking.manage")
def booking_details(vendor_id, booking_id):
    txs = Transaction.query.filter_by(booking_id=booking_id, vendor_id=vendor_id).all()
    booking = db.session.get(Booking, booking_id) if txs else None
    if not booking:
        return jsonify(success=False, error="Booking not found for this cafe."), 404
    from models.user import User
    from models.contactInfo import ContactInfo
    user = db.session.get(User, booking.user_id) if booking.user_id else None
    contact = ContactInfo.query.filter_by(parent_id=user.id, parent_type="user").first() if user else None
    meals = [{"name": e.extra_service_menu.name, "quantity": e.quantity, "total": float(e.total_price)}
             for e in booking.booking_extra_services if e.extra_service_menu]
    payload = details_payload(
        {"id": booking.id, "status": booking.status, "booking_mode": booking.booking_mode,
         "created_at": _iso(booking.created_at), "squad_details": booking.squad_details},
        [{"amount": t.amount, "total_with_tax": t.total_with_tax, "settlement_status": t.settlement_status,
          "payment_use_case": t.payment_use_case, "mode_of_payment": t.mode_of_payment, "source_channel": t.source_channel,
          "initiated_by_staff_name": t.initiated_by_staff_name, "initiated_by_staff_role": t.initiated_by_staff_role,
          "created_at": _iso(t.created_at)} for t in txs],
        {"name": user.name if user else None, "phone": contact.phone if contact else None, "email": contact.email if contact else None},
        meals,
    )
    db.session.rollback()  # read-only
    response = jsonify(success=True, booking=payload)
    response.headers["Cache-Control"] = "no-store"
    return response
