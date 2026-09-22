"""Enforce migrated cafe policies before legacy checkout can collect money."""
from flask import request, jsonify
from sqlalchemy import text
from db.extensions import db


def enforce_cafe_payment_policy():
    if request.method not in ('POST', 'PUT', 'PATCH'):
        return None
    endpoint = (request.endpoint or '').split('.')[-1]
    gaming = {'create_booking', 'confirm_booking', 'new_booking', 'direct_booking',
              'kiosk_book_next_slot', 'extra_booking', 'settle_pending_booking_transactions',
              'create_order', 'generate_payment_link', 'capture_payment'}
    food = {'add_meals_to_booking'}
    if endpoint not in gaming | food:
        return None
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(message='Invalid request body'), 400
    vendor_ids = set()
    args = request.view_args or {}
    requested_vendor = args.get('vendor_id') or body.get('vendor_id')
    if requested_vendor:
        try:
            vendor_ids.add(int(requested_vendor))
        except (ValueError, TypeError):
            return jsonify(message='Invalid cafe identifier'), 400
    game_id = body.get('game_id')
    if game_id:
        row = db.session.execute(text('SELECT vendor_id FROM available_games WHERE id=:id'), {'id':game_id}).first()
        if row:
            vendor_ids.add(row[0])
    booking_ids = body.get('booking_id') or args.get('booking_id')
    if booking_ids:
        booking_ids = booking_ids if isinstance(booking_ids, list) else [booking_ids]
        for bid in booking_ids:
            row = db.session.execute(text('SELECT ag.vendor_id FROM bookings b JOIN available_games ag ON ag.id=b.game_id WHERE b.id=:id'), {'id':bid}).first()
            if row:
                vendor_ids.add(row[0])
    if endpoint in {'create_order', 'generate_payment_link', 'capture_payment'} and not vendor_ids:
        return jsonify(message='Supply vendor_id, game_id or booking_id for payment policy validation.', code='cafe_context_required'), 400
    for vid in vendor_ids:
        row = db.session.execute(text('SELECT settings FROM cafe_payment_policies WHERE vendor_id=:vid'), {'vid':vid}).first()
        if row:
            settings = row[0]
            if endpoint in gaming:
                return jsonify(message='This cafe uses cafe wallet checkout. Scan the QR on your PC.', code='cafe_wallet_required'), 403
            if not settings.get('food_ordering') or settings.get('food_collection') == 'vendor':
                return jsonify(message='Food has a separate store checkout at this cafe.', code='separate_food_checkout'), 403
    return None
