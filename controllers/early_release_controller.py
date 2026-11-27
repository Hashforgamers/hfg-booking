"""Unused-time setting and early release of desk sessions (rules in services.early_release)."""
from flask import Blueprint, current_app, jsonify, request

from db.extensions import db
from services import early_release
from services.early_release import EarlyReleaseError
from services.vendor_access import require_vendor_permission

early_release_blueprint = Blueprint("early_release", __name__)


@early_release_blueprint.errorhandler(EarlyReleaseError)
def _handle(error):
    db.session.rollback()
    return jsonify(success=False, message=str(error)), error.status


def _booking_for_vendor(vendor_id, booking_id):
    from models.booking import Booking
    from models.availableGame import AvailableGame
    booking = (Booking.query.join(AvailableGame, AvailableGame.id == Booking.game_id)
               .filter(Booking.id == booking_id, AvailableGame.vendor_id == vendor_id).first())
    if not booking:
        raise EarlyReleaseError("Booking not found for this cafe", 404)
    return booking


def _ended_at(value):
    from services.overtime_quote import parse_played_until, OvertimeError
    try:
        return parse_played_until(value)
    except OvertimeError as error:
        raise EarlyReleaseError(str(error))


def _console(value):
    return int(value) if str(value or "").strip().isdigit() else None


@early_release_blueprint.route("/vendor/<int:vendor_id>/unused-time/settings", methods=["GET"])
@require_vendor_permission("booking.manage")
def get_settings(vendor_id):
    return jsonify(success=True, settings=early_release.load_settings(db.session, vendor_id),
                   policies=list(early_release.POLICIES), schema_ready=early_release.schema_ready(db.session))


@early_release_blueprint.route("/vendor/<int:vendor_id>/unused-time/settings", methods=["PUT"])
@require_vendor_permission("account.manage")
def put_settings(vendor_id):
    settings = early_release.save_settings(db.session, vendor_id, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(success=True, settings=settings)


@early_release_blueprint.route("/vendor/<int:vendor_id>/booking/<int:booking_id>/release-quote", methods=["GET"])
@require_vendor_permission("booking.manage")
def release_quote(vendor_id, booking_id):
    booking = _booking_for_vendor(vendor_id, booking_id)
    result = early_release.quote(db.session, vendor_id, booking, _console(request.args.get("console_id")),
                                 _ended_at(request.args.get("ended_at")))
    db.session.rollback()
    response = jsonify(success=True, quote=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@early_release_blueprint.route("/vendor/<int:vendor_id>/booking/<int:booking_id>/early-release", methods=["POST"])
@require_vendor_permission("booking.manage")
def record_early_release(vendor_id, booking_id):
    from controllers.booking_controller import calculate_gst_breakdown, resolve_transaction_actor
    data = request.get_json(silent=True) or {}
    booking = _booking_for_vendor(vendor_id, booking_id)
    record = early_release.apply(
        db.session, vendor_id, booking, mode=data.get("mode"), refund_method=data.get("refund_method"),
        console_id=_console(data.get("console_id")), ended_at=_ended_at(data.get("ended_at")),
        actor=resolve_transaction_actor(request, default_source="dashboard"),
        gst=lambda amount: calculate_gst_breakdown(vendor_id, amount))
    db.session.commit()
    if record.get("transaction_id") and not record.get("already_recorded"):
        try:
            from utils.realtime import emit_vendor_event
            emit_vendor_event(current_app.extensions.get("socketio"), "booking_payment_update",
                              {"transaction_id": record["transaction_id"], "booking_id": booking_id,
                               "payment_use_case": "early_release", "status": record["mode"]}, vendor_id)
        except Exception:
            current_app.logger.warning("early release emit failed booking=%s", booking_id)
    return jsonify(success=True, early_release=record)
