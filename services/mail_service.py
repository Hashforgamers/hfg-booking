# services/mail_service.py

from flask_mail import Message
from db.extensions import mail
from flask import current_app

def send_email(subject, recipients, body, html=None):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    if html:
        msg.html = html
    current_app.logger.info(f"msg: {msg}")
    try:
        mail.send(msg)
        current_app.logger.info("Mail Sent Successfully")
    except Exception as e:
        current_app.logger.error(f"Failed to send email: {e}")

    
def booking_mail(
    gamer_name,
    gamer_phone,
    gamer_email,
    cafe_name,
    booking_date,
    booked_for_date,
    booking_details,
    price_paid,
    extra_meals=None,  # new parameter, default None
    extra_controller_fare=0,
    waive_off_amount=0
):
    # booking_details = list of dicts: [{booking_id: 1, slot_time: "10:00 AM - 11:00 AM"}, ...]

    booking_table_rows = "".join([
        f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{b['booking_id']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{b['slot_time']}</td>
        </tr>
        """ for b in booking_details
    ])

    # Prepare extra meals rows if provided
    extra_meals_rows = ""
    total_extra_meals_price = 0
    if extra_meals:
        extra_meals_rows = """
        <h3 style="margin-top: 30px;">🍽️ Extra Meals & Services</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
            <thead>
                <tr style="background-color: #f0f0f0;">
                    <th style="padding: 8px; border: 1px solid #ddd;">Item</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Quantity</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Unit Price</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Total</th>
                </tr>
            </thead>
            <tbody>
        """
        for meal in extra_meals:
            name = meal.get("name")
            quantity = meal.get("quantity", 1)
            unit_price = meal.get("unit_price", 0)
            total_price = meal.get("total_price", 0)
            total_extra_meals_price += total_price
            extra_meals_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{name}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{quantity}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">₹{unit_price:.2f}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">₹{total_price:.2f}</td>
            </tr>
            """
        extra_meals_rows += "</tbody></table>"

    # Add extra controller fare row if given
    extra_controller_fare_row = ""
    if extra_controller_fare and extra_controller_fare > 0:
        extra_controller_fare_row = f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;" colspan="3"><strong>Extra Controller Fare</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">₹{extra_controller_fare:.2f}</td>
        </tr>
        """

    # Add waive-off row if given
    waive_off_row = ""
    if waive_off_amount and waive_off_amount > 0:
        waive_off_row = f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;" colspan="3"><strong>Waive Off Amount</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">-₹{waive_off_amount:.2f}</td>
        </tr>
        """

    final_price = price_paid  # this should already account for everything, just display

    send_email(
        subject="🎮 Booking Confirmed – Hash Gaming Café",
        recipients=[gamer_email],
        body="Your booking has been confirmed!",
        html=f"""<!DOCTYPE html>
        <html lang="en">
        <head><meta charset="UTF-8"><title>Booking Confirmation</title></head>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f6f6f6; margin: 0; padding: 0;">
        <div style="max-width: 640px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);">

            <div style="background: linear-gradient(to right, #000000, #550000); color: #fff; text-align: center; padding: 30px 20px;">
                <h1 style="margin: 0; font-size: 24px;">🎮 Booking Confirmed!</h1>
                <div style="font-size: 14px; color: #ccc; margin-top: 10px;">Your session is locked in. Game on!</div>
            </div>

            <div style="padding: 30px; color: #333;">
                <p>Hi <strong>{gamer_name}</strong>,</p>
                <p>Thanks for booking with <strong>{cafe_name}</strong> via Hash! Here are your booking details:</p>

                <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                    <tr><td style="padding: 8px; font-weight: bold;">Name:</td><td>{gamer_name}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Phone:</td><td>{gamer_phone}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Email:</td><td>{gamer_email}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Gaming Café:</td><td>{cafe_name}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Booking Date:</td><td>{booking_date}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Booked For:</td><td>{booked_for_date}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Price Paid:</td><td>₹{final_price:.2f}</td></tr>
                </table>

                <h3 style="margin-top: 30px;">🕒 Booking ID & Slot Time</h3>
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                    <thead>
                        <tr style="background-color: #f0f0f0;">
                            <th style="padding: 8px; border: 1px solid #ddd;">Booking ID</th>
                            <th style="padding: 8px; border: 1px solid #ddd;">Slot Time</th>
                        </tr>
                    </thead>
                    <tbody>
                        {booking_table_rows}
                        {extra_controller_fare_row}
                        {waive_off_row}
                    </tbody>
                </table>

                {extra_meals_rows}

                <p style="margin-top: 30px;">If you have any questions or need help, feel free to contact us. Enjoy your game!</p>
                <p>Cheers,<br><strong>The Hash Team</strong></p>
            </div>

            <div style="text-align: center; padding: 20px; font-size: 12px; color: #888; background-color: #fafafa;">
                &copy; 2025 Hash Platform. All rights reserved.
            </div>

        </div>
        </body>
        </html>"""
    )


def reject_booking_mail(gamer_name, gamer_email, cafe_name, reason="No reason provided"):
    send_email(
        subject="❌ Booking Not Confirmed – Hash Gaming Café",
        recipients=[gamer_email],
        body="Unfortunately, your booking request could not be confirmed.",  # Plain text fallback
        html=f"""<!DOCTYPE html>
        <html lang="en">
        <head>
        <meta charset="UTF-8">
        <title>Booking Rejected</title>
        </head>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f6f6f6; margin: 0; padding: 0;">
        <div style="max-width: 640px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);">

            <!-- Header -->
            <div style="background: linear-gradient(to right, #550000, #000000); color: #fff; text-align: center; padding: 30px 20px;">
            <h1 style="margin: 0; font-size: 24px;">❌ Booking Not Confirmed</h1>
            <div style="font-size: 14px; color: #ccc; margin-top: 10px;">We're sorry we couldn't process your request</div>
            </div>

            <!-- Content -->
            <div style="padding: 30px; color: #333;">
            <p>Hi <strong>{gamer_name}</strong>,</p>
            <p>Thank you for your interest in booking with <strong>{cafe_name}</strong> via Hash. Unfortunately, we were unable to confirm your booking request.</p>

            <p style="margin: 20px 0; background-color: #fbeaea; border-left: 4px solid #d32f2f; padding: 15px; color: #a30000;">
                <strong>Reason:</strong> {reason}
            </p>

            <p>If you'd like to try again, feel free to select a different date, time slot, or café through the Hash platform.</p>
            <p>We hope to serve you soon!</p>

            <p>Warm regards,<br><strong>The Hash Team</strong></p>
            </div>

            <!-- Footer -->
            <div style="text-align: center; padding: 20px; font-size: 12px; color: #888; background-color: #fafafa;">
            &copy; 2025 Hash Platform. All rights reserved.
            </div>

        </div>
        </body>
        </html>"""
    )

def extra_booking_time_mail(username, user_email, booked_date, slot_time, console_type, console_number, amount, mode_of_payment):
    send_email(
        subject="🎮 Extra Playtime – Payment Receipt from Hash Gaming Café",
        recipients=[user_email],
        body="Thanks for staying longer and gaming with us! Here's your payment receipt.",
        html=f"""<!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <title>Additional Payment Receipt</title>
        </head>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f6f6f6; margin: 0; padding: 0;">
          <div style="max-width: 640px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);">

            <div style="background: linear-gradient(to right, #000000, #550000); color: #fff; text-align: center; padding: 30px 20px;">
              <h1 style="margin: 0; font-size: 24px;">🎮 Extra Playtime Payment</h1>
              <div style="font-size: 14px; color: #ccc; margin-top: 10px;">Thanks for staying longer!</div>
            </div>

            <div style="padding: 30px; color: #333;">
              <p>Hi <strong>{username}</strong>,</p>
              <p>You enjoyed some extra gaming time on your recent visit! Here's a summary of the additional amount charged:</p>

              <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                <tr>
                  <td style="padding: 8px; font-weight: bold; color: #555;">Date of Booking:</td>
                  <td style="padding: 8px;">{booked_date}</td>
                </tr>
                <tr style="background-color: #f9f9f9;">
                  <td style="padding: 8px; font-weight: bold; color: #555;">Slot Time:</td>
                  <td style="padding: 8px;">{slot_time}</td>
                </tr>
                <tr>
                  <td style="padding: 8px; font-weight: bold; color: #555;">Console Type:</td>
                  <td style="padding: 8px;">{console_type}</td>
                </tr>
                <tr style="background-color: #f9f9f9;">
                  <td style="padding: 8px; font-weight: bold; color: #555;">Console Number:</td>
                  <td style="padding: 8px;">#{console_number}</td>
                </tr>
                <tr>
                  <td style="padding: 8px; font-weight: bold; color: #555;">Amount Paid:</td>
                  <td style="padding: 8px;">₹{amount}</td>
                </tr>
                <tr style="background-color: #f9f9f9;">
                  <td style="padding: 8px; font-weight: bold; color: #555;">Mode of Payment:</td>
                  <td style="padding: 8px;">{mode_of_payment}</td>
                </tr>
              </table>

              <p style="margin-top: 20px;">We appreciate your time with us. Keep gaming and have fun!</p>
              <p>Cheers,<br><strong>The Hash Team</strong></p>
            </div>

            <div style="text-align: center; padding: 20px; font-size: 12px; color: #888; background-color: #fafafa;">
              &copy; 2025 Hash Platform. All rights reserved.
            </div>

          </div>
        </body>
        </html>"""
    )
