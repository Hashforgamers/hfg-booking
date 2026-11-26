"""Price extra play (overtime) from the cafe's own desk rate card.

Pure functions only: no database or Flask access, so the same math can be
tested directly and copied into hfg-dashboard
(app/services/rate_card_pricing.py keeps an identical copy for kiosk play).

Rule: extra play costs the MARGINAL rate-card price of the whole session,
    quote(card, booked + extra, players) - quote(card, booked, players)
so the gamer keeps every benefit the owner designed: longer sessions reach
cheaper duration tiers, per-player and whole-group rules apply to the squad,
and game-title overrides still win. Callers then cap the result at the old
slot-rate price, so this pricing can only ever lower an overtime charge.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from services.desk_pricing import game_rate_key, legacy_definition, rates_for_game

CENT = Decimal(".01")


def _rule_for(definition, minutes, players):
    """The one rule covering this duration and squad size, or None.

    Durations are matched on whole minutes (a partly used minute counts as
    the next minute), so 119.5 minutes still finds the 120-180 tier instead
    of falling between two tiers.
    """
    whole = max(1, math.ceil(Decimal(str(minutes))))
    matches = [r for r in definition.get("rules") or []
               if int(r["min_minutes"]) <= whole
               and (r.get("max_minutes") is None or whole <= int(r["max_minutes"]))
               and int(r["min_players"]) <= players <= int(r["max_players"])]
    return matches[0] if len(matches) == 1 else None


def card_quote(definition, minutes, players):
    """Price of a session of `minutes` for `players` (same arithmetic as
    services.desk_pricing.quote), or None when no unique rule covers it."""
    minutes = Decimal(str(minutes))
    if minutes <= 0:
        return Decimal(0)
    rule = _rule_for(definition, minutes, players)
    if rule is None:
        return None
    total = Decimal(str(rule["amount"])) * (players if rule["per_player"] else 1)
    if int(rule.get("unit_minutes") or 0):
        total = total * minutes / Decimal(int(rule["unit_minutes"]))
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def marginal_extra(definition, booked_minutes, extra_minutes, players, paid_base=None):
    """Rate-card price of `extra_minutes` played after `booked_minutes`.

    1. quote(booked + extra) - quote(booked)
    2. when the booked part was a fixed package the card cannot quote:
       quote(booked + extra) - what the booking's base actually cost
    3. when no rule covers the whole session: quote(extra) on its own
    Returns a Decimal >= 0, or None when the card cannot price it at all.
    """
    players = max(1, int(players or 1))
    extra_minutes = Decimal(str(extra_minutes))
    if extra_minutes <= 0:
        return Decimal(0)
    booked_minutes = Decimal(str(max(0, booked_minutes or 0)))
    total = card_quote(definition, booked_minutes + extra_minutes, players)
    if total is not None:
        base = card_quote(definition, booked_minutes, players)
        if base is None and paid_base is not None:
            base = Decimal(str(paid_base))
        if base is not None:
            return max(Decimal(0), total - base)
    alone = card_quote(definition, extra_minutes, players)
    return None if alone is None else max(Decimal(0), alone)


def resolve_definition(card):
    return card.get("definition") or legacy_definition(card["profile"], card.get("rates") or [])


def candidate_cards(cards, *, pricing_mode="slot", stored_profile=None, game_title="", console_id=None):
    """Rate cards that may price this session, best match first.

    cards: rows of desk_rate_cards for the booking's vendor and game (dicts with
    profile, revision, definition/rates, is_active, archived).
    - only active, unarchived cards; a standard card counts only when the
      device is in variant pricing ('variants'), a game-title card always;
    - the card the booking was priced with (stored profile) wins outright;
    - otherwise a game-title override replaces the standard cards;
    - cards mapped to this physical console come before unmapped cards, and
      cards mapped only to other consoles are left out.
    """
    usable = []
    for card in cards or []:
        if not card.get("is_active", True) or card.get("archived"):
            continue
        try:
            definition = resolve_definition(card)
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        special = bool(game_rate_key(str(definition.get("game_variant") or "")))
        if pricing_mode != "variants" and not special:
            continue
        usable.append(dict(card, definition=definition))
    if stored_profile:
        own = [c for c in usable if c.get("profile") == stored_profile]
        if own:
            return own
    try:
        allowed = rates_for_game([c["definition"] for c in usable], game_title or "")
    except ValueError:
        allowed = rates_for_game([c["definition"] for c in usable], "")
    usable = [c for c in usable if c["definition"] in allowed]
    if console_id is not None:
        try:
            console = int(console_id)
        except (TypeError, ValueError):
            console = None
        if console is not None:
            mapped = [c for c in usable if console in (c["definition"].get("console_ids") or [])]
            if mapped:
                return mapped
    return [c for c in usable if not c["definition"].get("console_ids")] or (usable if console_id is None else [])


def best_extra_price(cards, booked_minutes, extra_minutes, players, paid_base=None):
    """(price, card) for the cheapest card that can price the extra play, or (None, None)."""
    best = (None, None)
    for card in cards:
        price = marginal_extra(card["definition"], booked_minutes, extra_minutes, players, paid_base)
        if price is not None and (best[0] is None or price < best[0]):
            best = (price, card)
    return best


def card_summary(card):
    if not card:
        return None
    return {"name": card["definition"].get("name"), "profile": card.get("profile"),
            "revision": card.get("revision")}
