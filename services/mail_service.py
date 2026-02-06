from flask_mail import Message
from db.extensions import mail
from flask import current_app


def send_email(subject, recipients, body, html=None):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    if html:
        msg.html = html

    try:
        mail.send(msg)
        current_app.logger.info(f"✅ Mail sent successfully to {recipients}")
    except Exception as e:
        current_app.logger.error(f"❌ Failed to send email: {e}")


# =========================
# BOOKING CONFIRMATION MAIL
# =========================
def booking_mail(
    gamer_name,
    gamer_phone,
    gamer_email,
    cafe_name,
    booking_date,
    booked_for_date,
    booking_details,
    price_paid,
    extra_meals=None,
    extra_controller_fare=0,
    waive_off_amount=0
):
    """
    Send booking confirmation email with optional meals
    """
    booking_rows = "".join(
        f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #2a2a2a;">{b['booking_id']}</td>
            <td style="padding:10px;border-bottom:1px solid #2a2a2a;">{b['slot_time']}</td>
        </tr>
        """
        for b in booking_details
    )

    extra_meals_html = ""
    if extra_meals:
        rows = ""
        total_meals_cost = 0
        for meal in extra_meals:
            meal_total = meal.get('total_price', 0)
            total_meals_cost += meal_total
            rows += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #2a3d2a;">{meal['name']}</td>
                <td style="padding:8px;text-align:center;border-bottom:1px solid #2a3d2a;">{meal.get('quantity', 1)}</td>
                <td style="padding:8px;text-align:right;border-bottom:1px solid #2a3d2a;">₹{meal.get('unit_price', 0):.2f}</td>
                <td style="padding:8px;text-align:right;border-bottom:1px solid #2a3d2a;">₹{meal_total:.2f}</td>
            </tr>
            """
        extra_meals_html = f"""
        <div style="margin-top:25px;background-color:#1f2a1f;border:1px solid #2a3d2a;border-radius:6px;padding:20px;">
            <h3 style="margin-top:0;color:#00ff88;">🍽️ Meals & Services</h3>
            <table style="width:100%;border-collapse:collapse;color:#ffffff;">
                <tr style="background-color:#0d1a0d;">
                    <th style="padding:8px;text-align:left;">Item</th>
                    <th style="padding:8px;text-align:center;">Qty</th>
                    <th style="padding:8px;text-align:right;">Price</th>
                    <th style="padding:8px;text-align:right;">Total</th>
                </tr>
                {rows}
                <tr>
                    <td colspan="3" style="padding:10px;text-align:right;font-weight:bold;color:#00ff88;">Meals Total:</td>
                    <td style="padding:10px;text-align:right;font-weight:bold;color:#00ff88;">₹{total_meals_cost:.2f}</td>
                </tr>
            </table>
        </div>
        """

    adjustments_html = ""
    if extra_controller_fare > 0:
        adjustments_html += f"""
        <tr>
            <td colspan="2" style="padding:10px;color:#00ff88;">
                Extra Controller Fare: ₹{extra_controller_fare:.2f}
            </td>
        </tr>
        """

    if waive_off_amount > 0:
        adjustments_html += f"""
        <tr>
            <td colspan="2" style="padding:10px;color:#ff6666;">
                Waive Off: -₹{waive_off_amount:.2f}
            </td>
        </tr>
        """

    send_email(
        subject="🎮 Booking Confirmed – Hash Gaming Café",
        recipients=[gamer_email],
        body="Your booking has been confirmed!",
        html=f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',sans-serif;background-color:#0d0d0d;margin:0;padding:0;">
<div style="max-width:640px;margin:auto;background-color:#141414;border-radius:8px;overflow:hidden;">

    <div style="padding:30px;text-align:center;background-color:#000000;">
        <img src="https://res.cloudinary.com/dxjjigepf/image/upload/v1755415904/Adobe_Express_-_file_1_wfe3ad.png" width="80">
        <h2 style="color:#ffffff;margin:10px 0;">🎮 Booking Confirmed</h2>
        <p style="color:#bbbbbb;">Built for Cafés, Made for Gamers</p>
    </div>

    <div style="padding:30px;color:#ffffff;">
        <p>Hi <strong>{gamer_name}</strong>,</p>
        <p>Your booking at <strong>{cafe_name}</strong> is confirmed.</p>

        <table style="width:100%;margin-top:20px;">
            <tr><td style="color:#bbbbbb;">Phone</td><td>{gamer_phone}</td></tr>
            <tr><td style="color:#bbbbbb;">Email</td><td>{gamer_email}</td></tr>
            <tr><td style="color:#bbbbbb;">Booking Date</td><td>{booking_date}</td></tr>
            <tr><td style="color:#bbbbbb;">Booked For</td><td>{booked_for_date}</td></tr>
            <tr><td style="color:#bbbbbb;">Price Paid</td><td style="color:#00ff88;">₹{price_paid:.2f}</td></tr>
        </table>

        <h3 style="margin-top:30px;color:#00ff88;">🕒 Slot Details</h3>
        <table style="width:100%;background-color:#1c1c1c;border:1px solid #2a2a2a;">
            <tr>
                <th style="padding:10px;">Booking ID</th>
                <th style="padding:10px;">Slot Time</th>
            </tr>
            {booking_rows}
            {adjustments_html}
        </table>

        {extra_meals_html}

        <p style="margin-top:25px;">Enjoy your game! 🎮</p>
        <p>Cheers,<br><strong>Team Hash</strong></p>
    </div>

    <div style="padding:20px;text-align:center;color:#666;font-size:12px;background:#222;">
        © 2025 Hash Platform. All rights reserved.
    </div>

</div>
</body>
</html>
"""
    )


# ========================================
# ✅ NEW: MEALS ADDED TO EXISTING BOOKING
# ========================================
def meals_added_mail(
    gamer_name,
    gamer_email,
    cafe_name,
    booking_id,
    slot_time,
    added_meals,
    meals_total,
    updated_booking_total,
    booking_date=None
):
    """
    Send notification email when meals are added to an existing active booking
    """
    meals_rows = ""
    for meal in added_meals:
        meals_rows += f"""
        <tr>
            <td style="padding:12px;border-bottom:1px solid #2a3d2a;">{meal['name']}</td>
            <td style="padding:12px;text-align:center;border-bottom:1px solid #2a3d2a;">{meal.get('quantity', 1)}</td>
            <td style="padding:12px;text-align:right;border-bottom:1px solid #2a3d2a;">₹{meal.get('unit_price', 0):.2f}</td>
            <td style="padding:12px;text-align:right;border-bottom:1px solid #2a3d2a;">₹{meal.get('total_price', 0):.2f}</td>
        </tr>
        """

    send_email(
        subject=f"🍽️ Meals Added to Your Booking #{booking_id} – Hash Gaming Café",
        recipients=[gamer_email],
        body=f"Meals have been added to your booking #{booking_id}",
        html=f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',sans-serif;background-color:#0d0d0d;margin:0;padding:0;">
<div style="max-width:640px;margin:auto;background-color:#141414;border-radius:8px;overflow:hidden;">

    <div style="padding:30px;text-align:center;background: linear-gradient(135deg, #1f2a1f 0%, #0d1a0d 100%);">
        <img src="https://res.cloudinary.com/dxjjigepf/image/upload/v1755415904/Adobe_Express_-_file_1_wfe3ad.png" width="80">
        <h2 style="color:#ffffff;margin:10px 0;">🍽️ Meals Added</h2>
        <p style="color:#bbbbbb;">Your order has been updated</p>
    </div>

    <div style="padding:30px;color:#ffffff;">
        <p>Hi <strong>{gamer_name}</strong>,</p>
        <p>We've added the following meals to your booking at <strong>{cafe_name}</strong>.</p>

        <div style="background-color:#1a1a1a;border-left:4px solid #00ff88;padding:15px;margin:20px 0;border-radius:4px;">
            <table style="width:100%;color:#ffffff;">
                <tr><td style="color:#bbbbbb;padding:5px 0;">Booking ID:</td><td style="text-align:right;"><strong>#{booking_id}</strong></td></tr>
                <tr><td style="color:#bbbbbb;padding:5px 0;">Slot Time:</td><td style="text-align:right;"><strong>{slot_time}</strong></td></tr>
                {f'<tr><td style="color:#bbbbbb;padding:5px 0;">Date:</td><td style="text-align:right;"><strong>{booking_date}</strong></td></tr>' if booking_date else ''}
            </table>
        </div>

        <h3 style="margin-top:30px;color:#00ff88;">🍔 Added Items</h3>
        <table style="width:100%;background-color:#1c1c1c;border:1px solid #2a3d2a;border-radius:6px;overflow:hidden;">
            <tr style="background-color:#0d1a0d;">
                <th style="padding:12px;text-align:left;">Item</th>
                <th style="padding:12px;text-align:center;">Qty</th>
                <th style="padding:12px;text-align:right;">Price</th>
                <th style="padding:12px;text-align:right;">Total</th>
            </tr>
            {meals_rows}
            <tr style="background-color:#1f2a1f;">
                <td colspan="3" style="padding:15px;text-align:right;font-weight:bold;color:#00ff88;font-size:16px;">
                    Meals Total:
                </td>
                <td style="padding:15px;text-align:right;font-weight:bold;color:#00ff88;font-size:16px;">
                    ₹{meals_total:.2f}
                </td>
            </tr>
        </table>

        <div style="background-color:#0d1a0d;border:2px solid #00ff88;padding:20px;margin:25px 0;border-radius:8px;text-align:center;">
            <p style="margin:0;color:#bbbbbb;font-size:14px;">Updated Booking Total</p>
            <p style="margin:10px 0 0 0;color:#00ff88;font-size:28px;font-weight:bold;">₹{updated_booking_total:.2f}</p>
        </div>

        <div style="background-color:#1a1a1a;border-left:4px solid #ffaa00;padding:15px;margin:20px 0;border-radius:4px;">
            <p style="margin:0;color:#ffaa00;font-weight:bold;">💰 Payment Note</p>
            <p style="margin:10px 0 0 0;color:#bbbbbb;font-size:14px;">
                The meal charges (₹{meals_total:.2f}) will be added to your final bill. Please settle the amount at the counter.
            </p>
        </div>

        <p style="margin-top:25px;">Enjoy your meal and gaming session! 🎮🍕</p>
        <p>Cheers,<br><strong>Team Hash</strong></p>
    </div>

    <div style="padding:20px;text-align:center;color:#666;font-size:12px;background:#222;">
        © 2025 Hash Platform. All rights reserved.
    </div>

</div>
</body>
</html>
"""
    )


# =================
# REJECTION MAIL
# =================
def reject_booking_mail(gamer_name, gamer_email, cafe_name, reason="No reason provided"):
    """
    Send booking rejection email
    """
    send_email(
        subject="❌ Booking Not Confirmed – Hash",
        recipients=[gamer_email],
        body="Your booking could not be confirmed.",
        html=f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',sans-serif;background-color:#0d0d0d;">
<div style="max-width:640px;margin:auto;background:#141414;border-radius:8px;">

    <div style="padding:30px;text-align:center;background:#550000;">
        <h2 style="color:#ffffff;">❌ Booking Rejected</h2>
    </div>

    <div style="padding:30px;color:#ffffff;">
        <p>Hi <strong>{gamer_name}</strong>,</p>
        <p>Your booking at <strong>{cafe_name}</strong> was not confirmed.</p>

        <div style="background:#2a0000;padding:15px;border-left:4px solid #ff4444;">
            <strong>Reason:</strong> {reason}
        </div>

        <p style="margin-top:20px;">We hope to serve you soon.</p>
        <p>— Team Hash</p>
    </div>

</div>
</body>
</html>
"""
    )


# ============================
# EXTRA TIME PAYMENT RECEIPT
# ============================
def extra_booking_time_mail(
    username,
    user_email,
    booked_date,
    slot_time,
    console_type,
    console_number,
    amount,
    mode_of_payment
):
    """
    Send extra playtime receipt email
    """
    send_email(
        subject="🎮 Extra Playtime Receipt – Hash",
        recipients=[user_email],
        body="Extra playtime payment receipt",
        html=f"""
<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',sans-serif;background:#0d0d0d;">
<div style="max-width:640px;margin:auto;background:#141414;border-radius:8px;">

    <div style="padding:30px;text-align:center;background:#000;">
        <h2 style="color:#ffffff;">🎮 Extra Playtime Receipt</h2>
    </div>

    <div style="padding:30px;color:#ffffff;">
        <p>Hi <strong>{username}</strong>,</p>

        <table style="width:100%;">
            <tr><td style="padding:8px 0;color:#bbbbbb;">Date</td><td style="text-align:right;">{booked_date}</td></tr>
            <tr><td style="padding:8px 0;color:#bbbbbb;">Slot</td><td style="text-align:right;">{slot_time}</td></tr>
            <tr><td style="padding:8px 0;color:#bbbbbb;">Console</td><td style="text-align:right;">{console_type} #{console_number}</td></tr>
            <tr><td style="padding:8px 0;color:#bbbbbb;">Amount</td><td style="text-align:right;color:#00ff88;font-weight:bold;">₹{amount}</td></tr>
            <tr><td style="padding:8px 0;color:#bbbbbb;">Payment Mode</td><td style="text-align:right;">{mode_of_payment}</td></tr>
        </table>

        <p style="margin-top:20px;">Thanks for gaming with us!</p>
        <p>— Team Hash</p>
    </div>

</div>
</body>
</html>
"""
    )
