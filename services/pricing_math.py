"""Pricing contract shared by the independently deployed booking and dashboard services.

Prices are INR per configured slot. Offers cover continuous IST intervals and
apply only when they cover the whole slot. Lowest valid price wins, capped by base.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def money(value, *, maximum=10000000):
    if isinstance(value, bool):
        raise ValueError('Price must be a number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid price')
    if not result.is_finite() or result < 0 or result > maximum or result != result.quantize(Decimal('0.01')):
        raise ValueError('Price must be non-negative with at most two decimal places')
    return result


def slot_window(day, start, end):
    left = datetime.combine(day, start)
    right = datetime.combine(day, end)
    if right <= left:
        right += timedelta(days=1)
    return left, right


def offer_window(offer):
    return datetime.combine(offer.start_date, offer.start_time), datetime.combine(offer.end_date, offer.end_time)


def effective_price(base, offers, start, end):
    prices = [money(base)]
    for offer in offers:
        left, right = offer_window(offer)
        if offer.is_active and left <= start and end <= right and left < right:
            prices.append(money(offer.offered_price))
    return min(prices)


def controller_total(base, tiers, quantity):
    if type(quantity) is not int or not 0 <= quantity <= 64:
        raise ValueError('Controller quantity must be an integer from 0 to 64')
    base = money(base)
    clean = []
    for tier in tiers:
        count, price = tier['quantity'], money(tier['total_price'])
        if type(count) is not int or not 2 <= count <= 64:
            raise ValueError('Controller tier quantity must be from 2 to 64')
        clean.append((count, price))
    dp = [Decimal('0')]
    for count in range(1, quantity + 1):
        dp.append(min([dp[count-1] + base] + [dp[count-size]+price for size,price in clean if size <= count]))
    return dp[quantity]


def session_amount(base, slots, offers, start, minutes):
    """Prorate each covered slot; fail closed on schedule gaps or overlaps."""
    if type(minutes) is not int or not 5 <= minutes <= 720:
        raise ValueError('Session duration must be between 5 and 720 minutes')
    end = start + timedelta(minutes=minutes)
    windows = []
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        for slot in slots:
            scheduled_day = getattr(slot, 'date', None)
            if scheduled_day is not None and scheduled_day != day:
                continue
            left,right = slot_window(day,slot.start_time,slot.end_time)
            if left < end and start < right:
                windows.append((left,right,slot))
        day += timedelta(days=1)
    windows.sort(key=lambda row:(row[0],row[1]))
    cursor, total = start, Decimal('0')
    for left,right,slot in windows:
        overlap_start, overlap_end = max(start,left), min(end,right)
        if overlap_start != cursor:
            raise ValueError('Console slots overlap or do not cover this session; update the console schedule')
        price = effective_price(base, offers, left, right)
        total += price * Decimal(str((overlap_end-overlap_start).total_seconds())) / Decimal(str((right-left).total_seconds()))
        cursor = overlap_end
    if cursor != end:
        raise ValueError('Console schedule does not cover this session')
    return int((total * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
