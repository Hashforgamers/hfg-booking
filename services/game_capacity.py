"""Keep a game's sellable capacity equal to the consoles actually mapped to it.

available_games.total_slot and the dated VENDOR_<id>_SLOT.available_slot rows were
seeded from the console count at generation time. Consoles added, re-typed or
re-linked outside the dashboard's add-console path left them stale, so a cafe with
11 PCs could only sell the old count. Shifting by the difference keeps every
booking's earlier deduction intact.
"""
from datetime import datetime

from pytz import timezone
from sqlalchemy import text

from db.extensions import db

IST = timezone("Asia/Kolkata")


def mapped_console_count(vendor_id, game_id):
    return int(db.session.execute(text("""
        SELECT COUNT(DISTINCT c.id)
        FROM available_game_console agc
        JOIN consoles c ON c.id = agc.console_id AND c.vendor_id = :vendor
        WHERE agc.available_game_id = :game
    """), {"vendor": int(vendor_id), "game": int(game_id)}).scalar() or 0)


def sync_game_capacity(vendor_id, game_id):
    """Return the game's capacity, syncing it first when it drifted.

    Reads without locking; only a mismatch takes the row lock and commits, so a
    plain slot read never holds locks or rolls back the caller's work.
    """
    vendor_id, game_id = int(vendor_id), int(game_id)
    actual = mapped_console_count(vendor_id, game_id)
    current = db.session.execute(text(
        "SELECT total_slot FROM available_games WHERE id=:game AND vendor_id=:vendor"),
        {"game": game_id, "vendor": vendor_id}).scalar()
    if current is None:
        return 0
    if actual <= 0 or actual == int(current or 0):
        return int(current or 0) if actual <= 0 else actual
    try:
        locked = db.session.execute(text(
            "SELECT total_slot FROM available_games WHERE id=:game FOR UPDATE"), {"game": game_id}).scalar()
        delta = actual - int(locked or 0)
        if delta:
            today = datetime.now(IST).date()
            db.session.execute(text("UPDATE available_games SET total_slot=:total WHERE id=:game"),
                               {"total": actual, "game": game_id})
            db.session.execute(text("""
                UPDATE slots SET available_slot = GREATEST(COALESCE(available_slot, 0) + :delta, 0)
                WHERE gaming_type_id = :game
            """), {"delta": delta, "game": game_id})
            db.session.execute(text(f"""
                UPDATE VENDOR_{vendor_id}_SLOT
                SET available_slot = GREATEST(COALESCE(available_slot, 0) + :delta, 0),
                    is_available = GREATEST(COALESCE(available_slot, 0) + :delta, 0) > 0
                WHERE vendor_id = :vendor AND date >= :today
                  AND slot_id IN (SELECT id FROM slots WHERE gaming_type_id = :game)
            """), {"delta": delta, "vendor": vendor_id, "today": today, "game": game_id})
        db.session.commit()
        if delta:
            from flask import current_app
            current_app.logger.warning("game_capacity.synced vendor=%s game=%s %s->%s",
                                       vendor_id, game_id, int(locked or 0), actual)
        return actual
    except Exception:
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception("game_capacity.sync_failed vendor=%s game=%s", vendor_id, game_id)
        return int(current or 0)
