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
        current_app.logger.info("Mail Sent Successfully")
    except Exception as e:
        current_app.logger.error(f"Failed to send email: {e}")


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
        for meal in extra_meals:
            rows += f"""
            <tr>
                <td style="padding:8px;">{meal['name']}</td>
                <td style="padding:8px;text-align:center;">{meal.get('quantity',1)}</td>
                <td style="padding:8px;text-align:right;">₹{meal.get('total_price',0):.2f}</td>
            </tr>
            """
        extra_meals_html = f"""
        <div style="margin-top:25px;background-color:#1f2a1f;border:1px solid #2a3d2a;border-radius:6px;padding:20px;">
            <h3 style="margin-top:0;color:#00ff88;">🍽️ Extra Meals & Services</h3>
            <table style="width:100%;border-collapse:collapse;color:#ffffff;">
                {rows}
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


# =================
# REJECTION MAIL
# =================
def reject_booking_mail(gamer_name, gamer_email, cafe_name, reason="No reason provided"):

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
            <tr><td>Date</td><td>{booked_date}</td></tr>
            <tr><td>Slot</td><td>{slot_time}</td></tr>
            <tr><td>Console</td><td>{console_type} #{console_number}</td></tr>
            <tr><td>Amount</td><td style="color:#00ff88;">₹{amount}</td></tr>
            <tr><td>Payment Mode</td><td>{mode_of_payment}</td></tr>
        </table>

        <p style="margin-top:20px;">Thanks for gaming with us!</p>
        <p>— Team Hash</p>
    </div>

</div>
</body>
</html>
"""
    )
