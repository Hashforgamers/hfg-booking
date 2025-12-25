# controllers/pass_controller.py
from flask import Blueprint, request, jsonify, current_app, g
from services.pass_service import PassService
from services.security import auth_required_self
from db.extensions import db
from models.passModels import UserPass, CafePass, PassRedemptionLog
from models.transaction import Transaction  # ✅ ADD this (used in purchase_pass)
from decimal import Decimal
from datetime import datetime, timedelta, time as time_type  # ✅ timedelta added
from sqlalchemy import or_  # ✅ ADD this
import razorpay
import pytz

IST = pytz.timezone("Asia/Kolkata")

pass_blueprint = Blueprint('pass', __name__)

@pass_blueprint.route('/pass/validate', methods=['POST'])
def validate_pass():
    """
    Validate pass UID and return pass details.
    Used by dashboard before redemption.
    """
    try:
        data = request.get_json()
        pass_uid = data.get('pass_uid')
        vendor_id = data.get('vendor_id')
        
        if not pass_uid or not vendor_id:
            return jsonify({'error': 'pass_uid and vendor_id required'}), 400
        
        # Find pass
        user_pass = UserPass.query.filter_by(
            pass_uid=pass_uid,
            is_active=True,
            pass_mode='hour_based'
        ).first()
        
        if not user_pass:
            return jsonify({
                'valid': False,
                'error': 'Invalid or inactive pass'
            }), 404
        
        # Check expiry
        if user_pass.valid_to and user_pass.valid_to < datetime.now(IST).date():
            return jsonify({
                'valid': False,
                'error': 'Pass expired'
            }), 400
        
        # Check hours
        if user_pass.remaining_hours <= 0:
            return jsonify({
                'valid': False,
                'error': 'No hours remaining'
            }), 400
        
        # Check vendor compatibility
        cafe_pass = user_pass.cafe_pass
        if cafe_pass.vendor_id:
            if cafe_pass.vendor_id != vendor_id:
                return jsonify({
                    'valid': False,
                    'error': 'Pass not valid at this vendor'
                }), 400
        
        # Return pass details
        return jsonify({
            'valid': True,
            'pass': {
                'id': user_pass.id,
                'pass_uid': user_pass.pass_uid,
                'user_id': user_pass.user_id,
                'pass_name': cafe_pass.name,
                'total_hours': float(user_pass.total_hours),
                'remaining_hours': float(user_pass.remaining_hours),
                'valid_from': user_pass.valid_from.isoformat() if user_pass.valid_from else None,
                'valid_to': user_pass.valid_to.isoformat() if user_pass.valid_to else None,
                'is_global': cafe_pass.vendor_id is None,
                'vendor_id': cafe_pass.vendor_id,
                'hour_calculation_mode': cafe_pass.hour_calculation_mode,
                'hours_per_slot': float(cafe_pass.hours_per_slot) if cafe_pass.hours_per_slot else None
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Pass validation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@pass_blueprint.route('/pass/redeem/dashboard', methods=['POST'])
def redeem_pass_dashboard():
    """
    Redeem pass from dashboard (manual staff entry).
    """
    try:
        data = request.get_json()
        pass_uid = data.get('pass_uid')
        vendor_id = data.get('vendor_id')
        hours_to_deduct = data.get('hours_to_deduct')
        session_start = data.get('session_start')  # HH:MM format
        session_end = data.get('session_end')      # HH:MM format
        staff_id = data.get('staff_id')            # Dashboard user ID
        notes = data.get('notes')
        
        if not all([pass_uid, vendor_id, hours_to_deduct]):
            return jsonify({'error': 'pass_uid, vendor_id, and hours_to_deduct required'}), 400
        
        try:
            hours_decimal = Decimal(str(hours_to_deduct))
            if hours_decimal <= 0:
                return jsonify({'error': 'hours_to_deduct must be positive'}), 400
        except:
            return jsonify({'error': 'Invalid hours_to_deduct format'}), 400
        
        # Parse times if provided
        start_time = None
        end_time = None
        if session_start:
            try:
                start_time = datetime.strptime(session_start, '%H:%M').time()
            except:
                return jsonify({'error': 'Invalid session_start format (use HH:MM)'}), 400
        if session_end:
            try:
                end_time = datetime.strptime(session_end, '%H:%M').time()
            except:
                return jsonify({'error': 'Invalid session_end format (use HH:MM)'}), 400
        
        # Get pass
        user_pass = PassService.get_valid_user_pass(
            user_id=None,  # Will be determined from pass_uid
            vendor_id=vendor_id,
            pass_uid=pass_uid
        )
        
        if not user_pass:
            return jsonify({'error': 'Pass not found or invalid'}), 404
        
        # Redeem
        redemption = PassService.redeem_pass_hours(
            user_pass_id=user_pass.id,
            vendor_id=vendor_id,
            hours_to_deduct=hours_decimal,
            redemption_method='dashboard_manual',
            session_start=start_time,
            session_end=end_time,
            redeemed_by_staff_id=staff_id,
            notes=notes
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Pass redeemed successfully',
            'redemption': redemption.to_dict(),
            'remaining_hours': float(user_pass.remaining_hours),
            'is_depleted': user_pass.remaining_hours <= 0
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Dashboard redemption error: {str(e)}")
        return jsonify({'error': 'Redemption failed'}), 500

@pass_blueprint.route('/pass/redeem/app', methods=['POST'])
@auth_required_self(decrypt_user=True)
def redeem_pass_app():
    """
    Redeem pass during app booking flow.
    Called during booking confirmation.
    """
    try:
        user_id = g.auth_user_id
        data = request.get_json()
        
        vendor_id = data.get('vendor_id')
        slot_id = data.get('slot_id')
        pass_uid = data.get('pass_uid')  # Optional: specific pass
        booking_id = data.get('booking_id')
        
        if not all([vendor_id, slot_id, booking_id]):
            return jsonify({'error': 'vendor_id, slot_id, and booking_id required'}), 400
        
        # Get pass (specific or best available)
        user_pass = PassService.get_valid_user_pass(
            user_id=user_id,
            vendor_id=vendor_id,
            pass_uid=pass_uid
        )
        
        if not user_pass:
            return jsonify({'error': 'No valid pass found'}), 404
        
        # Calculate hours based on slot and pass config
        hours_to_deduct = PassService.calculate_slot_hours(
            slot_id=slot_id,
            cafe_pass=user_pass.cafe_pass
        )
        
        # Get slot times
        from models.slot import Slot
        slot = Slot.query.get(slot_id)
        
        # Redeem
        redemption = PassService.redeem_pass_hours(
            user_pass_id=user_pass.id,
            vendor_id=vendor_id,
            hours_to_deduct=hours_to_deduct,
            redemption_method='app_booking',
            booking_id=booking_id,
            session_start=slot.start_time if slot else None,
            session_end=slot.end_time if slot else None
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Pass redeemed for booking',
            'redemption': redemption.to_dict(),
            'hours_deducted': float(hours_to_deduct),
            'remaining_hours': float(user_pass.remaining_hours),
            'pass_uid': user_pass.pass_uid
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"App redemption error: {str(e)}")
        return jsonify({'error': 'Redemption failed'}), 500

@pass_blueprint.route('/pass/user/active', methods=['GET'])
@auth_required_self(decrypt_user=True)
def get_user_active_passes():
    """
    Get all active passes for authenticated user.
    """
    try:
        user_id = g.auth_user_id
        vendor_id = request.args.get('vendor_id', type=int)
        
        passes = PassService.get_user_active_passes(user_id, vendor_id)
        
        return jsonify({
            'passes': [p.to_dict() for p in passes]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get active passes error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@pass_blueprint.route('/pass/<int:user_pass_id>/history', methods=['GET'])
def get_pass_history(user_pass_id):
    """
    Get redemption history for a pass.
    """
    try:
        logs = PassRedemptionLog.query.filter_by(
            user_pass_id=user_pass_id
        ).order_by(PassRedemptionLog.redeemed_at.desc()).all()
        
        return jsonify({
            'history': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get pass history error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@pass_blueprint.route('/pass/redemption/<int:redemption_id>/cancel', methods=['POST'])
def cancel_redemption(redemption_id):
    """
    Cancel a redemption and restore hours.
    """
    try:
        data = request.get_json()
        reason = data.get('reason')
        
        success = PassService.cancel_redemption(redemption_id, reason)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Redemption cancelled and hours restored'
            }), 200
        else:
            return jsonify({'error': 'Cancellation failed'}), 500
            
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Cancel redemption error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@pass_blueprint.route('/pass/create-hour-pass', methods=['POST'])
@auth_required_self(decrypt_user=True)
def create_hour_pass():
    """
    Create hour-based pass after purchase (called after payment confirmation).
    """
    try:
        user_id = g.auth_user_id
        data = request.get_json()
        
        cafe_pass_id = data.get('cafe_pass_id')
        payment_details = data.get('payment_details')
        
        if not cafe_pass_id:
            return jsonify({'error': 'cafe_pass_id required'}), 400
        
        user_pass = PassService.create_hour_based_pass(
            user_id=user_id,
            cafe_pass_id=cafe_pass_id,
            payment_details=payment_details
        )
        
        return jsonify({
            'success': True,
            'message': 'Hour-based pass created',
            'pass': user_pass.to_dict()
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create hour pass error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# File: controllers/pass_controller.py
# ADD THIS ROUTE:

@pass_blueprint.route('/user/passes/purchase', methods=['POST'])
def purchase_pass():
    """
    User purchases a pass after Razorpay payment.
    Creates UserPass record with unique pass_uid.
    """
    try:
        
        IST = pytz.timezone("Asia/Kolkata")
        data = request.get_json()
        
        user_id = data.get('user_id')
        cafe_pass_id = data.get('cafe_pass_id')
        payment_id = data.get('payment_id')  # Razorpay payment ID
        payment_mode = data.get('payment_mode', 'payment_gateway')  # or 'wallet'
        
        if not all([user_id, cafe_pass_id]):
            return jsonify({'error': 'user_id and cafe_pass_id required'}), 400
        
        # Get cafe pass
        cafe_pass = CafePass.query.get(cafe_pass_id)
        if not cafe_pass or not cafe_pass.is_active:
            return jsonify({'error': 'Pass not available'}), 404
        
        # Verify Razorpay payment if payment_gateway
        if payment_mode == 'payment_gateway':
            if not payment_id:
                return jsonify({'error': 'payment_id required'}), 400
            
            try:
                RAZORPAY_KEY_ID = current_app.config.get("RAZORPAY_KEY_ID")
                RAZORPAY_KEY_SECRET = current_app.config.get("RAZORPAY_KEY_SECRET")
                razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                
                payment = razorpay_client.payment.fetch(payment_id)
                if payment['status'] != 'captured':
                    return jsonify({'error': 'Payment not successful'}), 400
                    
            except razorpay.errors.RazorpayError as e:
                return jsonify({'error': f'Payment verification failed: {str(e)}'}), 400
        
        # Deduct from wallet if wallet payment
        elif payment_mode == 'wallet':
            from models.user import User
            user = User.query.get(user_id)
            if not user or user.wallet_balance < cafe_pass.price:
                return jsonify({'error': 'Insufficient wallet balance'}), 400
            user.wallet_balance -= cafe_pass.price
        
        # Create UserPass based on pass_mode
        if cafe_pass.pass_mode == 'hour_based':
            # Use PassService for hour-based
            user_pass = PassService.create_hour_based_pass(
                user_id=user_id,
                cafe_pass_id=cafe_pass_id,
                payment_details={'payment_id': payment_id, 'mode': payment_mode}
            )
        else:
            # Create date-based pass
            valid_from = datetime.now(IST).date()
            valid_to = valid_from + timedelta(days=cafe_pass.days_valid)
            
            user_pass = UserPass(
                user_id=user_id,
                cafe_pass_id=cafe_pass_id,
                pass_mode='date_based',
                valid_from=valid_from,
                valid_to=valid_to,
                is_active=True,
                purchased_at=datetime.now(IST)
            )
            db.session.add(user_pass)
            db.session.flush()
        
        # Create transaction record
        transaction = Transaction(
            user_id=user_id,
            vendor_id=cafe_pass.vendor_id,
            user_name=user_pass.user.name if user_pass.user else None,
            original_amount=cafe_pass.price,
            discounted_amount=0,
            amount=cafe_pass.price,
            mode_of_payment=payment_mode,
            booking_date=datetime.now(IST).date(),
            booking_time=datetime.now(IST).time(),
            reference_id=payment_id,
            # Add custom field if needed: transaction_type='pass_purchase'
        )
        db.session.add(transaction)
        db.session.commit()
        
        current_app.logger.info(
            f"Pass purchased: user_id={user_id} pass_id={user_pass.id} "
            f"amount={cafe_pass.price} payment={payment_mode}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Pass purchased successfully',
            'user_pass': user_pass.to_dict(),
            'transaction_id': transaction.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Pass purchase failed: {str(e)}")
        return jsonify({'error': str(e)}), 500


# File: controllers/pass_controller.py
# ADD THIS ROUTE:

@pass_blueprint.route('/vendor/<int:vendor_id>/passes/available', methods=['GET'])
def get_available_passes_for_purchase(vendor_id):
    """
    Get all active passes available for purchase at a vendor.
    Used by user app to show passes for sale.
    """
    try:
        
        # Get vendor-specific AND global passes
        passes = CafePass.query.filter(
            CafePass.is_active == True,
            or_(
                CafePass.vendor_id == vendor_id,
                CafePass.vendor_id.is_(None)  # Global passes
            )
        ).order_by(CafePass.pass_mode, CafePass.price).all()
        
        return jsonify({
            'passes': [p.to_dict() for p in passes]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get available passes error: {str(e)}")
        return jsonify({'error': str(e)}), 500
