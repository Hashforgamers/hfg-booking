# controllers/private_booking_controller.py

from flask import Blueprint, request, jsonify, current_app
from services.booking_service import BookingService
from models.availableGame import AvailableGame
from models.extraServiceMenu import ExtraServiceMenu
from db.extensions import db
from datetime import datetime, time
from decimal import Decimal
import pytz

private_booking_blueprint = Blueprint('private_booking', __name__)

@private_booking_blueprint.route('/booking/private', methods=['POST'])
def create_private_booking():
    """
    Create a private booking from vendor dashboard.
    Does NOT check slot availability.
    """
    try:
        data = request.get_json()
        
        # Extract data
        vendor_id = data.get('vendor_id')
        user_info = data.get('user_info', {})
        game_id = data.get('game_id')
        booking_date_str = data.get('booking_date')
        start_time_str = data.get('start_time')
        end_time_str = data.get('end_time')
        duration_hours = data.get('duration_hours')
        hourly_rate = data.get('hourly_rate')
        extra_services = data.get('extra_services', [])
        payment_mode = data.get('payment_mode', 'Cash')
        manual_discount = data.get('manual_discount', 0)
        waive_off_amount = data.get('waive_off_amount', 0)
        notes = data.get('notes', '')
        
        current_app.logger.info(f"Private booking request: {data}")
        
        # Validate required fields
        if not all([vendor_id, user_info.get('name'), user_info.get('email'), 
                    user_info.get('phone'), game_id, booking_date_str, 
                    start_time_str, end_time_str]):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400
        
        # Parse date
        try:
            if 'T' in booking_date_str:
                booking_date = datetime.fromisoformat(booking_date_str).date()
            else:
                booking_date = datetime.strptime(booking_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid booking_date format'
            }), 400
        
        # Parse times
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid time format. Use HH:MM'
            }), 400
        
        # Calculate duration if not provided
        if not duration_hours:
            start_dt = datetime.combine(booking_date, start_time)
            end_dt = datetime.combine(booking_date, end_time)
            if end_dt < start_dt:
                from datetime import timedelta
                end_dt += timedelta(days=1)
            duration_hours = (end_dt - start_dt).total_seconds() / 3600
        
        # Convert to Decimal
        duration_hours = Decimal(str(duration_hours))
        hourly_rate = Decimal(str(hourly_rate))
        manual_discount = Decimal(str(manual_discount))
        waive_off_amount = Decimal(str(waive_off_amount))
        
        # Get socketio instance
        socketio = current_app.extensions.get('socketio')
        
        # Create private booking
        booking = BookingService.create_private_booking(
            vendor_id=vendor_id,
            user_info=user_info,
            game_id=game_id,
            booking_date=booking_date,
            start_time=start_time,
            end_time=end_time,
            duration_hours=duration_hours,
            hourly_rate=hourly_rate,
            extra_services=extra_services,
            payment_mode=payment_mode,
            manual_discount=manual_discount,
            waive_off_amount=waive_off_amount,
            notes=notes,
            socketio=socketio
        )
        
        # Calculate final amount
        slot_cost = float(hourly_rate * duration_hours)
        extras_total = sum([
            ExtraServiceMenu.query.get(e['item_id']).price * e['quantity']
            for e in extra_services
            if ExtraServiceMenu.query.get(e['item_id'])
        ])
        total_amount = slot_cost + extras_total - float(manual_discount) - float(waive_off_amount)
        
        return jsonify({
            'success': True,
            'message': 'Private booking created successfully',
            'booking': {
                'booking_id': booking.id,
                'booking_mode': 'private',
                'user_id': booking.user_id,
                'game_id': booking.game_id,
                'date': str(booking_date),
                'start_time': str(start_time),
                'end_time': str(end_time),
                'duration_hours': float(duration_hours),
                'hourly_rate': float(hourly_rate),
                'total_amount': total_amount,
                'payment_mode': payment_mode,
                'status': booking.status
            }
        }), 201
        
    except ValueError as e:
        current_app.logger.error(f"Private booking validation error: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creating private booking")
        return jsonify({
            'success': False,
            'message': f'Failed to create private booking: {str(e)}'
        }), 500


@private_booking_blueprint.route('/booking/private/<int:booking_id>', methods=['GET'])
def get_private_booking(booking_id):
    """Get details of a private booking"""
    try:
        from models.booking import Booking
        
        booking = Booking.query.filter_by(
            id=booking_id,
            booking_mode='private'
        ).first()
        
        if not booking:
            return jsonify({
                'success': False,
                'message': 'Private booking not found'
            }), 404
        
        return jsonify({
            'success': True,
            'booking': booking.to_dict()
        }), 200
        
    except Exception as e:
        current_app.logger.exception("Error fetching private booking")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@private_booking_blueprint.route('/vendor/<int:vendor_id>/bookings/private', methods=['GET'])
def get_vendor_private_bookings(vendor_id):
    """Get all private bookings for a vendor"""
    try:
        from models.booking import Booking
        from sqlalchemy import and_
        
        date_filter = request.args.get('date')
        
        query = db.session.query(Booking).join(AvailableGame).filter(
            and_(
                Booking.booking_mode == 'private',
                AvailableGame.vendor_id == vendor_id
            )
        )
        
        if date_filter:
            try:
                filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
                query = query.join(Booking.transaction).filter(
                    db.func.date(Booking.transaction.booked_date) == filter_date
                )
            except ValueError:
                pass
        
        bookings = query.order_by(Booking.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'bookings': [b.to_dict() for b in bookings]
        }), 200
        
    except Exception as e:
        current_app.logger.exception("Error fetching vendor private bookings")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
