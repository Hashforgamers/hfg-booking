# services/pass_service.py
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta, time as time_type
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app
from db.extensions import db
from models.passModels import UserPass
from models.passModels import CafePass
from models.passModels import PassRedemptionLog
from models.vendor import Vendor
from models.slot import Slot
import pytz

IST = pytz.timezone("Asia/Kolkata")

class PassService:
    
    @staticmethod
    def calculate_slot_hours(slot_id: int, cafe_pass: CafePass) -> Decimal:
        """
        Calculate hours for a slot based on pass configuration.
        
        Args:
            slot_id: Slot ID
            cafe_pass: CafePass object with hour_calculation_mode
            
        Returns:
            Decimal: Hours to deduct
        """
        slot = Slot.query.get(slot_id)
        if not slot:
            raise ValueError(f"Slot {slot_id} not found")
        
        if cafe_pass.hour_calculation_mode == 'vendor_config':
            # Vendor sets fixed hours per slot
            return Decimal(str(cafe_pass.hours_per_slot or 1.0))
        
        else:  # 'actual_duration'
            # Calculate based on actual slot duration
            start_dt = datetime.combine(date.today(), slot.start_time)
            end_dt = datetime.combine(date.today(), slot.end_time)
            
            # Handle overnight slots
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            
            duration_seconds = (end_dt - start_dt).total_seconds()
            duration_hours = Decimal(str(duration_seconds / 3600))
            
            # Round to 2 decimal places
            return duration_hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    @staticmethod
    def get_valid_user_pass(
        user_id: int, 
        vendor_id: int, 
        pass_uid: str = None,
        check_date: date = None
    ) -> UserPass:
        """
        Get valid hour-based pass for user.
        
        Priority:
        1. If pass_uid provided, validate that specific pass
        2. Otherwise, find best available pass (vendor-specific first, then global)
        
        Args:
            user_id: User ID
            vendor_id: Vendor ID where pass will be used
            pass_uid: Optional pass UID for specific pass
            check_date: Date to check validity (default: today)
            
        Returns:
            UserPass object or None
        """
        if check_date is None:
            check_date = datetime.now(IST).date()
        
        base_query = db.session.query(UserPass).join(CafePass).filter(
            UserPass.user_id == user_id,
            UserPass.is_active == True,
            UserPass.pass_mode == 'hour_based',
            UserPass.remaining_hours > 0,
            or_(
                UserPass.valid_to.is_(None),  # No expiry
                UserPass.valid_to >= check_date
            )
        )
        
        # If specific pass_uid provided
        if pass_uid:
            user_pass = base_query.filter(UserPass.pass_uid == pass_uid).first()
            if not user_pass:
                raise ValueError(f"Pass {pass_uid} not found or invalid")
            
            # Check vendor compatibility
            if user_pass.cafe_pass.vendor_id:
                if user_pass.cafe_pass.vendor_id != vendor_id:
                    raise ValueError(f"Pass {pass_uid} is not valid at this vendor")
            
            return user_pass
        
        # Otherwise, find best available pass
        # Priority: Vendor-specific > Global
        vendor_pass = base_query.filter(CafePass.vendor_id == vendor_id).first()
        if vendor_pass:
            return vendor_pass
        
        global_pass = base_query.filter(CafePass.vendor_id.is_(None)).first()
        return global_pass
    
    @staticmethod
    def redeem_pass_hours(
        user_pass_id: int,
        vendor_id: int,
        hours_to_deduct: Decimal,
        redemption_method: str,
        booking_id: int = None,
        session_start: time_type = None,
        session_end: time_type = None,
        redeemed_by_staff_id: int = None,
        notes: str = None
    ) -> PassRedemptionLog:
        """
        Deduct hours from pass and create redemption log.
        
        Args:
            user_pass_id: UserPass ID
            vendor_id: Vendor ID
            hours_to_deduct: Hours to deduct (Decimal)
            redemption_method: 'dashboard_manual' or 'app_booking'
            booking_id: Optional booking ID (for app bookings)
            session_start: Session start time
            session_end: Session end time
            redeemed_by_staff_id: Staff user ID (for dashboard redemptions)
            notes: Optional notes
            
        Returns:
            PassRedemptionLog object
            
        Raises:
            ValueError: If insufficient hours or invalid pass
        """
        try:
            # Lock the user_pass row for update
            user_pass = db.session.query(UserPass).filter(
                UserPass.id == user_pass_id
            ).with_for_update().first()
            
            if not user_pass:
                raise ValueError(f"Pass {user_pass_id} not found")
            
            if not user_pass.is_active:
                raise ValueError(f"Pass {user_pass.pass_uid} is inactive")
            
            if user_pass.pass_mode != 'hour_based':
                raise ValueError(f"Pass {user_pass.pass_uid} is not hour-based")
            
            # Check expiry
            if user_pass.valid_to and user_pass.valid_to < datetime.now(IST).date():
                raise ValueError(f"Pass {user_pass.pass_uid} has expired")
            
            # Check sufficient balance
            if user_pass.remaining_hours < hours_to_deduct:
                raise ValueError(
                    f"Insufficient hours. Required: {hours_to_deduct}, "
                    f"Available: {user_pass.remaining_hours}"
                )
            
            # Deduct hours
            user_pass.remaining_hours -= hours_to_deduct
            
            # Deactivate if depleted
            if user_pass.remaining_hours <= 0:
                user_pass.is_active = False
            
            # Create redemption log
            redemption = PassRedemptionLog(
                user_pass_id=user_pass_id,
                booking_id=booking_id,
                vendor_id=vendor_id,
                user_id=user_pass.user_id,
                hours_deducted=hours_to_deduct,
                session_start_time=session_start,
                session_end_time=session_end,
                redemption_method=redemption_method,
                redeemed_by_staff_id=redeemed_by_staff_id,
                notes=notes
            )
            
            db.session.add(redemption)
            db.session.flush()
            
            current_app.logger.info(
                f"Pass redeemed: pass_id={user_pass_id} uid={user_pass.pass_uid} "
                f"hours={hours_to_deduct} remaining={user_pass.remaining_hours} "
                f"method={redemption_method}"
            )
            
            return redemption
            
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Pass redemption failed: {str(e)}")
            raise ValueError(f"Failed to redeem pass: {str(e)}")
    
    @staticmethod
    def cancel_redemption(redemption_id: int, reason: str = None) -> bool:
        """
        Cancel a redemption and restore hours to pass.
        
        Args:
            redemption_id: PassRedemptionLog ID
            reason: Cancellation reason
            
        Returns:
            bool: Success status
        """
        try:
            redemption = PassRedemptionLog.query.get(redemption_id)
            if not redemption:
                raise ValueError(f"Redemption {redemption_id} not found")
            
            if redemption.is_cancelled:
                raise ValueError(f"Redemption {redemption_id} already cancelled")
            
            # Lock user_pass for update
            user_pass = db.session.query(UserPass).filter(
                UserPass.id == redemption.user_pass_id
            ).with_for_update().first()
            
            if not user_pass:
                raise ValueError(f"Pass not found")
            
            # Restore hours
            user_pass.remaining_hours += redemption.hours_deducted
            
            # Reactivate if was deactivated due to zero balance
            if not user_pass.is_active and user_pass.remaining_hours > 0:
                if not user_pass.valid_to or user_pass.valid_to >= datetime.now(IST).date():
                    user_pass.is_active = True
            
            # Mark redemption as cancelled
            redemption.is_cancelled = True
            redemption.cancelled_at = datetime.now(IST)
            if reason:
                redemption.notes = f"{redemption.notes or ''}\nCancelled: {reason}".strip()
            
            db.session.commit()
            
            current_app.logger.info(
                f"Redemption cancelled: redemption_id={redemption_id} "
                f"hours_restored={redemption.hours_deducted}"
            )
            
            return True
            
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Redemption cancellation failed: {str(e)}")
            return False
    
    @staticmethod
    def create_hour_based_pass(
        user_id: int,
        cafe_pass_id: int,
        payment_details: dict = None
    ) -> UserPass:
        """
        Create hour-based user pass after purchase.
        
        Args:
            user_id: User ID
            cafe_pass_id: CafePass ID
            payment_details: Optional payment info for logging
            
        Returns:
            UserPass object
        """
        cafe_pass = CafePass.query.get(cafe_pass_id)
        if not cafe_pass:
            raise ValueError(f"CafePass {cafe_pass_id} not found")
        
        if cafe_pass.pass_mode != 'hour_based':
            raise ValueError(f"CafePass {cafe_pass_id} is not hour-based")
        
        if not cafe_pass.is_active:
            raise ValueError(f"CafePass {cafe_pass_id} is inactive")
        
        # Generate unique UID
        pass_uid = UserPass.generate_pass_uid()
        while UserPass.query.filter_by(pass_uid=pass_uid).first():
            pass_uid = UserPass.generate_pass_uid()
        
        # Calculate validity dates (optional for hour-based)
        valid_from = datetime.now(IST).date()
        valid_to = None
        if cafe_pass.days_valid:
            valid_to = valid_from + timedelta(days=cafe_pass.days_valid)
        
        user_pass = UserPass(
            user_id=user_id,
            cafe_pass_id=cafe_pass_id,
            pass_mode='hour_based',
            pass_uid=pass_uid,
            total_hours=cafe_pass.total_hours,
            remaining_hours=cafe_pass.total_hours,
            valid_from=valid_from,
            valid_to=valid_to,
            is_active=True,
            purchased_at=datetime.now(IST)
        )
        
        db.session.add(user_pass)
        db.session.commit()
        
        current_app.logger.info(
            f"Hour-based pass created: user_id={user_id} pass_id={user_pass.id} "
            f"uid={pass_uid} hours={cafe_pass.total_hours}"
        )
        
        return user_pass
    
    @staticmethod
    def get_user_active_passes(user_id: int, vendor_id: int = None) -> list:
        """
        Get all active passes for user (both date-based and hour-based).
        
        Args:
            user_id: User ID
            vendor_id: Optional vendor ID to filter passes
            
        Returns:
            List of UserPass objects
        """
        query = db.session.query(UserPass).join(CafePass).filter(
            UserPass.user_id == user_id,
            UserPass.is_active == True
        )
        
        # Filter hour-based passes by remaining hours
        query = query.filter(
            or_(
                UserPass.pass_mode == 'date_based',
                and_(
                    UserPass.pass_mode == 'hour_based',
                    UserPass.remaining_hours > 0
                )
            )
        )
        
        # Filter by vendor if specified
        if vendor_id:
            query = query.filter(
                or_(
                    CafePass.vendor_id == vendor_id,
                    CafePass.vendor_id.is_(None)  # Global passes
                )
            )
        
        return query.order_by(UserPass.purchased_at.desc()).all()
