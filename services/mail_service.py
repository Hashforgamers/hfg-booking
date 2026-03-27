import html
from typing import Iterable

from flask import current_app
from flask_mail import Message

from db.extensions import mail
from services.email_template import build_hfg_email_html


def _to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe(value) -> str:
    return html.escape(str(value or ""))


def _normalize_recipients(recipients: Iterable[str]) -> list[str]:
    if isinstance(recipients, str):
        recipients = [recipients]
    normalized = []
    for item in recipients or []:
        email = str(item or "").strip()
        if email:
            normalized.append(email)
    return normalized


def send_email(subject, recipients, body, html_fragment=None):
    recipient_list = _normalize_recipients(recipients)
    if not recipient_list:
        current_app.logger.warning("Skipping email '%s' because recipient list is empty", subject)
        return

    msg = Message(subject, recipients=recipient_list)
    msg.body = body
    msg.html = build_hfg_email_html(
        subject=subject,
        content_html=html_fragment or f"<p>{_safe(body)}</p>",
        preview_text=body,
    )

    try:
        mail.send(msg)
        current_app.logger.info("Mail sent successfully to %s", recipient_list)
    except Exception as exc:
        current_app.logger.error("Failed to send email '%s' to %s: %s", subject, recipient_list, exc)


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
    waive_off_amount=0,
    app_fee_amount=0,
    net_total=None,
):
    booking_rows = "".join(
        f"""
        <tr>
            <td style=\"padding:10px;border-bottom:1px solid #1e2a44;\">#{_safe(item.get('booking_id'))}</td>
            <td style=\"padding:10px;border-bottom:1px solid #1e2a44;\">{_safe(item.get('slot_time'))}</td>
        </tr>
        """
        for item in (booking_details or [])
    )

    meals_section = ""
    if extra_meals:
        meal_rows = []
        meals_total = 0.0
        for meal in extra_meals:
            qty = _to_float(meal.get("quantity", 1), 1)
            unit_price = _to_float(meal.get("unit_price", 0))
            total_price = _to_float(meal.get("total_price", unit_price * qty))
            meals_total += total_price
            meal_rows.append(
                f"""
                <tr>
                    <td style=\"padding:8px;border-bottom:1px solid #1e2a44;\">{_safe(meal.get('name'))}</td>
                    <td style=\"padding:8px;text-align:center;border-bottom:1px solid #1e2a44;\">{int(qty)}</td>
                    <td style=\"padding:8px;text-align:right;border-bottom:1px solid #1e2a44;\">₹{unit_price:.2f}</td>
                    <td style=\"padding:8px;text-align:right;border-bottom:1px solid #1e2a44;\">₹{total_price:.2f}</td>
                </tr>
                """
            )

        meals_section = f"""
        <div style=\"margin-top:20px;\">
            <div style=\"font-size:14px;font-weight:700;color:#22c55e;margin-bottom:8px;\">Meals and Extras</div>
            <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
                <tr style=\"background:#050f23;color:#cbd5e1;\">
                    <th style=\"padding:8px;text-align:left;\">Item</th>
                    <th style=\"padding:8px;text-align:center;\">Qty</th>
                    <th style=\"padding:8px;text-align:right;\">Unit</th>
                    <th style=\"padding:8px;text-align:right;\">Total</th>
                </tr>
                {''.join(meal_rows)}
                <tr>
                    <td colspan=\"3\" style=\"padding:10px;text-align:right;color:#22c55e;font-weight:700;\">Meals Total</td>
                    <td style=\"padding:10px;text-align:right;color:#22c55e;font-weight:700;\">₹{meals_total:.2f}</td>
                </tr>
            </table>
        </div>
        """

    paid_amount = _to_float(price_paid)
    platform_fee = _to_float(app_fee_amount)
    net_amount = _to_float(net_total, max(paid_amount - platform_fee, 0.0))
    extra_controller_fare = _to_float(extra_controller_fare)
    waive_off_amount = _to_float(waive_off_amount)

    adjustments = ""
    if extra_controller_fare > 0:
        adjustments += f"""
        <tr>
            <td colspan=\"2\" style=\"padding:10px;color:#22c55e;\">Extra Controller Fare: ₹{extra_controller_fare:.2f}</td>
        </tr>
        """
    if waive_off_amount > 0:
        adjustments += f"""
        <tr>
            <td colspan=\"2\" style=\"padding:10px;color:#f87171;\">Waive Off: -₹{waive_off_amount:.2f}</td>
        </tr>
        """

    content = f"""
    <p style=\"margin:0 0 12px 0;\">Hi <strong>{_safe(gamer_name)}</strong>,</p>
    <p style=\"margin:0 0 16px 0;color:#cbd5e1;\">Your booking at <strong>{_safe(cafe_name)}</strong> is confirmed.</p>

    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr><td style=\"padding:9px;color:#94a3b8;\">Phone</td><td style=\"padding:9px;\">{_safe(gamer_phone)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Email</td><td style=\"padding:9px;\">{_safe(gamer_email)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Booking Date</td><td style=\"padding:9px;\">{_safe(booking_date)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Booked For</td><td style=\"padding:9px;\">{_safe(booked_for_date)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Total Paid</td><td style=\"padding:9px;color:#22c55e;font-weight:700;\">₹{paid_amount:.2f}</td></tr>
      {f'<tr><td style="padding:9px;color:#94a3b8;">Platform Fee</td><td style="padding:9px;color:#facc15;">₹{platform_fee:.2f}</td></tr>' if platform_fee > 0 else ''}
      {f'<tr><td style="padding:9px;color:#94a3b8;">Net to Cafe</td><td style="padding:9px;color:#86efac;">₹{net_amount:.2f}</td></tr>' if platform_fee > 0 else ''}
    </table>

    <div style=\"font-size:14px;font-weight:700;color:#22c55e;margin:20px 0 8px;\">Slot Details</div>
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr style=\"background:#050f23;color:#cbd5e1;\">
        <th style=\"padding:10px;text-align:left;\">Booking ID</th>
        <th style=\"padding:10px;text-align:left;\">Slot Time</th>
      </tr>
      {booking_rows}
      {adjustments}
    </table>

    {meals_section}

    <p style=\"margin-top:18px;color:#cbd5e1;\">Enjoy your session and have fun.</p>
    """

    send_email(
        subject="Booking Confirmed - Hash For Gamers",
        recipients=[gamer_email],
        body="Your booking has been confirmed.",
        html_fragment=content,
    )


def meals_added_mail(
    gamer_name,
    gamer_email,
    cafe_name,
    booking_id,
    slot_time,
    added_meals,
    meals_total,
    updated_booking_total,
    booking_date=None,
    app_fee_amount=0,
    net_total=None,
):
    meal_rows = ""
    for meal in (added_meals or []):
        qty = int(_to_float(meal.get("quantity", 1), 1))
        unit_price = _to_float(meal.get("unit_price", 0))
        total_price = _to_float(meal.get("total_price", 0))
        meal_rows += f"""
        <tr>
          <td style=\"padding:8px;border-bottom:1px solid #1e2a44;\">{_safe(meal.get('name'))}</td>
          <td style=\"padding:8px;text-align:center;border-bottom:1px solid #1e2a44;\">{qty}</td>
          <td style=\"padding:8px;text-align:right;border-bottom:1px solid #1e2a44;\">₹{unit_price:.2f}</td>
          <td style=\"padding:8px;text-align:right;border-bottom:1px solid #1e2a44;\">₹{total_price:.2f}</td>
        </tr>
        """

    app_fee_amount = _to_float(app_fee_amount)
    updated_booking_total = _to_float(updated_booking_total)
    resolved_net_total = _to_float(net_total, max(updated_booking_total - app_fee_amount, 0.0))
    meals_total = _to_float(meals_total)

    content = f"""
    <p style=\"margin:0 0 12px 0;\">Hi <strong>{_safe(gamer_name)}</strong>,</p>
    <p style=\"margin:0 0 16px 0;color:#cbd5e1;\">Meals were added to your booking at <strong>{_safe(cafe_name)}</strong>.</p>

    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr><td style=\"padding:9px;color:#94a3b8;\">Booking ID</td><td style=\"padding:9px;\">#{_safe(booking_id)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Slot Time</td><td style=\"padding:9px;\">{_safe(slot_time)}</td></tr>
      {f'<tr><td style="padding:9px;color:#94a3b8;">Date</td><td style="padding:9px;">{_safe(booking_date)}</td></tr>' if booking_date else ''}
    </table>

    <div style=\"font-size:14px;font-weight:700;color:#22c55e;margin:20px 0 8px;\">Added Items</div>
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr style=\"background:#050f23;color:#cbd5e1;\">
        <th style=\"padding:8px;text-align:left;\">Item</th>
        <th style=\"padding:8px;text-align:center;\">Qty</th>
        <th style=\"padding:8px;text-align:right;\">Unit</th>
        <th style=\"padding:8px;text-align:right;\">Total</th>
      </tr>
      {meal_rows}
      <tr>
        <td colspan=\"3\" style=\"padding:10px;text-align:right;color:#22c55e;font-weight:700;\">Meals Total</td>
        <td style=\"padding:10px;text-align:right;color:#22c55e;font-weight:700;\">₹{meals_total:.2f}</td>
      </tr>
    </table>

    <div style=\"margin-top:14px;border:1px solid #1e2a44;background:#08142c;border-radius:8px;padding:12px;\">
      <div style=\"color:#94a3b8;font-size:13px;\">Updated Booking Total</div>
      <div style=\"margin-top:4px;color:#22c55e;font-size:24px;font-weight:700;\">₹{updated_booking_total:.2f}</div>
      {f'<div style="margin-top:6px;color:#facc15;">Platform Fee: ₹{app_fee_amount:.2f}</div>' if app_fee_amount > 0 else ''}
      {f'<div style="margin-top:4px;color:#86efac;">Net to Cafe: ₹{resolved_net_total:.2f}</div>' if app_fee_amount > 0 else ''}
    </div>

    <p style=\"margin-top:14px;color:#cbd5e1;\">Meal charges will be added to your final bill and settled at the cafe.</p>
    """

    send_email(
        subject=f"Meals Added to Booking #{booking_id} - Hash For Gamers",
        recipients=[gamer_email],
        body=f"Meals were added to your booking #{booking_id}.",
        html_fragment=content,
    )


def reject_booking_mail(gamer_name, gamer_email, cafe_name, reason="No reason provided"):
    content = f"""
    <p style=\"margin:0 0 12px 0;\">Hi <strong>{_safe(gamer_name)}</strong>,</p>
    <p style=\"margin:0 0 12px 0;color:#cbd5e1;\">Your booking at <strong>{_safe(cafe_name)}</strong> was not confirmed.</p>
    <div style=\"border:1px solid #7f1d1d;background:#2b0b10;border-radius:8px;padding:12px;color:#fecaca;\">
      <div style=\"font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#fca5a5;margin-bottom:4px;\">Reason</div>
      {_safe(reason)}
    </div>
    <p style=\"margin-top:14px;color:#cbd5e1;\">You can book another slot anytime from the app.</p>
    """

    send_email(
        subject="Booking Not Confirmed - Hash For Gamers",
        recipients=[gamer_email],
        body="Your booking could not be confirmed.",
        html_fragment=content,
    )


def extra_booking_time_mail(
    username,
    user_email,
    booked_date,
    slot_time,
    console_type,
    console_number,
    amount,
    mode_of_payment,
    app_fee_amount=0,
):
    amount = _to_float(amount)
    app_fee_amount = _to_float(app_fee_amount)
    net_amount = max(amount - app_fee_amount, 0.0)

    content = f"""
    <p style=\"margin:0 0 12px 0;\">Hi <strong>{_safe(username)}</strong>,</p>
    <p style=\"margin:0 0 12px 0;color:#cbd5e1;\">Your extra playtime receipt is ready.</p>
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr><td style=\"padding:9px;color:#94a3b8;\">Date</td><td style=\"padding:9px;\">{_safe(booked_date)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Slot</td><td style=\"padding:9px;\">{_safe(slot_time)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Console</td><td style=\"padding:9px;\">{_safe(console_type)} #{_safe(console_number)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Amount</td><td style=\"padding:9px;color:#22c55e;font-weight:700;\">₹{amount:.2f}</td></tr>
      {f'<tr><td style="padding:9px;color:#94a3b8;">Platform Fee</td><td style="padding:9px;color:#facc15;">₹{app_fee_amount:.2f}</td></tr>' if app_fee_amount > 0 else ''}
      {f'<tr><td style="padding:9px;color:#94a3b8;">Net to Cafe</td><td style="padding:9px;color:#86efac;">₹{net_amount:.2f}</td></tr>' if app_fee_amount > 0 else ''}
      <tr><td style=\"padding:9px;color:#94a3b8;\">Payment Mode</td><td style=\"padding:9px;\">{_safe(mode_of_payment)}</td></tr>
    </table>
    """

    send_email(
        subject="Extra Playtime Receipt - Hash For Gamers",
        recipients=[user_email],
        body="Extra playtime payment receipt.",
        html_fragment=content,
    )


def vendor_booking_notification_mail(
    vendor_email,
    cafe_name,
    booking_date,
    booked_for_date,
    payment_type,
    booking_details,
    total_amount_paid,
    total_app_fee=0,
    net_total_paid=None,
    notification_type="booking_confirmed",
    gamer_name=None,
    accept_action_url=None,
    reject_action_url=None,
    dashboard_url=None,
):
    booking_rows = "".join(
        f"""
        <tr>
          <td style=\"padding:10px;border-bottom:1px solid #1e2a44;\">#{_safe(item.get('booking_id'))}</td>
          <td style=\"padding:10px;border-bottom:1px solid #1e2a44;\">{_safe(item.get('gamer_name') or 'Guest')}</td>
          <td style=\"padding:10px;border-bottom:1px solid #1e2a44;\">{_safe(item.get('slot_time'))}</td>
          <td style=\"padding:10px;text-align:right;border-bottom:1px solid #1e2a44;\">₹{_to_float(item.get('amount_paid')):.2f}</td>
        </tr>
        """
        for item in (booking_details or [])
    )

    total_amount_paid = _to_float(total_amount_paid)
    total_app_fee = _to_float(total_app_fee)
    resolved_net_total = _to_float(net_total_paid, max(total_amount_paid - total_app_fee, 0.0))

    normalized_type = str(notification_type or "booking_confirmed").strip().lower()
    is_pending_request = normalized_type in {"booking_requested", "pending", "pending_acceptance"}
    status_heading = "New App Booking Request" if is_pending_request else "App Booking Confirmed"
    status_subtitle = (
        "Action required: please accept or reject this request from dashboard."
        if is_pending_request
        else "Booking confirmed from Hash app."
    )
    amount_label = "Estimated Amount" if is_pending_request else "Total Paid"
    action_note = (
        "Use the quick action buttons below, or review this request in your Pay at Cafe panel."
        if is_pending_request
        else "Please prepare the slot for the customer."
    )
    action_buttons = ""
    if is_pending_request and (accept_action_url or reject_action_url):
        button_cells = []
        if accept_action_url:
            button_cells.append(
                f"""
                <td style=\"padding:0 8px 0 0;\">
                    <a href=\"{html.escape(str(accept_action_url))}\"
                       style=\"display:inline-block;padding:10px 18px;border-radius:8px;background:#16a34a;color:#ffffff;text-decoration:none;font-weight:700;\">
                        Accept
                    </a>
                </td>
                """
            )
        if reject_action_url:
            button_cells.append(
                f"""
                <td style=\"padding:0;\">
                    <a href=\"{html.escape(str(reject_action_url))}\"
                       style=\"display:inline-block;padding:10px 18px;border-radius:8px;background:#dc2626;color:#ffffff;text-decoration:none;font-weight:700;\">
                        Reject
                    </a>
                </td>
                """
            )
        action_buttons = f"""
        <div style=\"margin-top:18px;\">
          <div style=\"margin:0 0 8px 0;color:#cbd5e1;font-size:13px;\">Quick Actions</div>
          <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\">
            <tr>
              {''.join(button_cells)}
            </tr>
          </table>
          {f'<p style="margin:10px 0 0 0;color:#94a3b8;font-size:12px;">Open dashboard: <a href="{html.escape(str(dashboard_url))}" style="color:#60a5fa;text-decoration:none;">{html.escape(str(dashboard_url))}</a></p>' if dashboard_url else ''}
        </div>
        """

    content = f"""
    <p style=\"margin:0 0 8px 0;\">Hello <strong>{_safe(cafe_name)}</strong>,</p>
    <p style=\"margin:0 0 16px 0;color:#cbd5e1;\">{_safe(status_subtitle)}</p>

    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr><td style=\"padding:9px;color:#94a3b8;\">Confirmation Date</td><td style=\"padding:9px;\">{_safe(booking_date)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Booked For</td><td style=\"padding:9px;\">{_safe(booked_for_date)}</td></tr>
      <tr><td style=\"padding:9px;color:#94a3b8;\">Payment Type</td><td style=\"padding:9px;\">{_safe(payment_type)}</td></tr>
      {f'<tr><td style="padding:9px;color:#94a3b8;">Customer</td><td style="padding:9px;">{_safe(gamer_name)}</td></tr>' if gamer_name else ''}
      <tr><td style=\"padding:9px;color:#94a3b8;\">{_safe(amount_label)}</td><td style=\"padding:9px;color:#22c55e;font-weight:700;\">₹{total_amount_paid:.2f}</td></tr>
      {f'<tr><td style="padding:9px;color:#94a3b8;">Platform Fee</td><td style="padding:9px;color:#facc15;">₹{total_app_fee:.2f}</td></tr>' if total_app_fee > 0 else ''}
      {f'<tr><td style="padding:9px;color:#94a3b8;">Net to Cafe</td><td style="padding:9px;color:#86efac;">₹{resolved_net_total:.2f}</td></tr>' if total_app_fee > 0 else ''}
    </table>

    <div style=\"font-size:14px;font-weight:700;color:#22c55e;margin:20px 0 8px;\">Slot Details</div>
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #1e2a44;border-radius:8px;overflow:hidden;background:#08142c;\">
      <tr style=\"background:#050f23;color:#cbd5e1;\">
        <th style=\"padding:10px;text-align:left;\">Booking ID</th>
        <th style=\"padding:10px;text-align:left;\">Customer</th>
        <th style=\"padding:10px;text-align:left;\">Slot Time</th>
        <th style=\"padding:10px;text-align:right;\">Amount</th>
      </tr>
      {booking_rows}
    </table>

    <p style=\"margin-top:16px;color:#cbd5e1;\">{_safe(action_note)}</p>
    {action_buttons}
    """

    send_email(
        subject=f"{status_heading} - {str(cafe_name or '').strip()}",
        recipients=[vendor_email],
        body=f"{status_heading}: {cafe_name}",
        html_fragment=content,
    )
