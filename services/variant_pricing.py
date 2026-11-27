"""Rate-card (variant) devices priced for channels that add up slot prices.

Bhanu, 2026-11-27: app and website bookings on a device in variant pricing
pay the desk's default rate instead of the plain slot price. The rule itself
is services.desk_pricing.default_variant_slot_price; this module loads the
cards (cached per request) for the slot listings and checkout.
"""
from sqlalchemy.sql import text

from db.extensions import db


def load_variant_definitions(vendor_id, game_id):
    """Active rate cards of a device whose desk pricing mode is 'variants' ([] otherwise)."""
    from services.desk_pricing import legacy_definition
    try:
        rows = db.session.execute(text("""SELECT c.profile,c.rates,c.definition FROM desk_rate_cards c
            JOIN desk_pricing_settings s ON s.vendor_id=c.vendor_id AND s.game_id=c.game_id AND s.mode='variants'
            WHERE c.vendor_id=:v AND c.game_id=:g AND c.is_active=true AND c.archived=false
            ORDER BY c.profile"""), {"v": int(vendor_id), "g": int(game_id)}).mappings().all()
    except Exception:
        return []  # rate-card tables missing (older database): plain slot pricing
    definitions = []
    for row in rows:
        try:
            definitions.append(row["definition"] or legacy_definition(row["profile"], row["rates"] or []))
        except (ValueError, KeyError, TypeError, IndexError):
            continue
    return definitions


def _cache():
    try:
        from flask import g
        return g.setdefault("_variant_cards", {})
    except RuntimeError:
        return {}


def variant_slot_price(vendor_id, game_id, slot_minutes, players=1):
    """Default rate-card price of one slot, or None (not in variant pricing, or not
    summable per slot: see default_variant_slot_price)."""
    if vendor_id is None or game_id is None:
        return None
    cache = _cache()
    key = (int(vendor_id), int(game_id))
    if key not in cache:
        cache[key] = load_variant_definitions(*key)
    if not cache[key]:
        return None
    from services.desk_pricing import default_variant_slot_price
    return default_variant_slot_price(cache[key], slot_minutes, players)
