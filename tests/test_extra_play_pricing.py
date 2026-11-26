"""Extra play is priced from the cafe's own rate card (marginal session price),
capped at the old slot-rate charge so it can only help the gamer."""
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services import extra_play_pricing as epp
from services import overtime_quote as oq
from tests.test_overtime_quote import fake_session, models, row  # noqa: F401  (fixture)


def rule(amount, low=1, high=None, players_low=1, players_high=1000, unit=60, each=False):
    return dict(amount=str(amount), min_minutes=low, max_minutes=high, min_players=players_low,
                max_players=players_high, unit_minutes=unit, per_player=each)


def card(profile, rules, variant="", consoles=None, name=None, revision=1):
    return dict(profile=profile, revision=revision, is_active=True, archived=False, rates=None,
                definition=dict(name=name or profile, model_name="m", game_variant=variant,
                                console_ids=consoles or [], rules=rules))


TIERED = [rule(60, 1, 119), rule(50, 120, 180), rule(30, 181)]


def test_tier_benefit_is_marginal_price_of_the_whole_session():
    # 60 booked + 60 extra = 120 min at Rs 50/h = Rs 100; booked 60 cost Rs 60.
    assert epp.marginal_extra(card("a", TIERED)["definition"], 60, 60, 1) == Decimal("40.00")


def test_fractional_minutes_do_not_fall_between_tiers():
    assert epp.card_quote(card("a", TIERED)["definition"], Decimal("119.5"), 1) is not None


def test_per_player_rule_prices_the_whole_squad():
    d = card("a", [rule(40, 1, None, each=True)])["definition"]
    assert epp.marginal_extra(d, 60, 30, 3) == Decimal("60.00")  # 3 x Rs 40/h x 0.5h


def test_group_rules_pick_the_squad_size():
    d = card("a", [rule(100, players_low=1, players_high=1), rule(150, players_low=2, players_high=4)])["definition"]
    assert epp.marginal_extra(d, 60, 60, 1) == Decimal("100.00")
    assert epp.marginal_extra(d, 60, 60, 3) == Decimal("150.00")


def test_fixed_package_uses_paid_base_then_extra_alone():
    # Flat 30-min and 60-min packages (racing sim style).
    d = card("r", [rule(200, 30, 30, unit=0), rule(300, 60, 60, unit=0)])["definition"]
    assert epp.marginal_extra(d, 30, 30, 1) == Decimal("100.00")
    # Booked 45 min (not a package) for Rs 250: 60 min costs 300 -> Rs 50 more.
    assert epp.marginal_extra(d, 45, 15, 1, paid_base=250) == Decimal("50.00")
    # Nothing covers 40 min, 10 min or the extra alone -> card cannot price it.
    assert epp.marginal_extra(d, 30, 10, 1) is None


def test_game_variant_override_replaces_standard_cards():
    cards = [card("std", TIERED), card("gta", [rule(120)], variant="GTA6")]
    assert [c["profile"] for c in epp.candidate_cards(cards, pricing_mode="variants", game_title="GTA 6")] == ["gta"]
    assert [c["profile"] for c in epp.candidate_cards(cards, pricing_mode="variants", game_title="")] == ["std"]
    # Slot-priced device: only game-title cards may price it.
    assert epp.candidate_cards(cards, pricing_mode="slot", game_title="") == []


def test_stored_profile_and_console_mapping():
    cards = [card("a", TIERED, consoles=[7]), card("b", TIERED), card("c", TIERED, consoles=[8])]
    assert [c["profile"] for c in epp.candidate_cards(cards, pricing_mode="variants", console_id=7)] == ["a"]
    assert [c["profile"] for c in epp.candidate_cards(cards, pricing_mode="variants", console_id=9)] == ["b"]
    assert [c["profile"] for c in epp.candidate_cards(cards, pricing_mode="variants", stored_profile="c", console_id=7)] == ["c"]
    inactive = [dict(cards[0], archived=True), cards[1]]
    assert [c["profile"] for c in epp.candidate_cards(inactive, pricing_mode="variants", console_id=7)] == ["b"]


def test_cheapest_card_wins_when_several_match():
    cards = epp.candidate_cards([card("a", [rule(80)]), card("b", [rule(60)])], pricing_mode="variants")
    price, chosen = epp.best_extra_price(cards, 60, 60, 1)
    assert price == Decimal("60.00") and chosen["profile"] == "b"


# ---- overtime_quote.quote integration -------------------------------------------------

OWN = [dict(row(5, time(20, 0), time(21, 0)), user_id=1, console_id=3, book_status="current")]


@pytest.fixture
def hourly_models(models, monkeypatch):
    import sys
    sys.modules["models.availableGame"].AvailableGame.query.filter_by.return_value.first.return_value = \
        SimpleNamespace(single_slot_price=60)
    sys.modules["models.slot"].Slot.query.filter_by.return_value.first.return_value = \
        SimpleNamespace(start_time=time(20, 0), end_time=time(21, 0))


def booking(**details):
    return SimpleNamespace(id=5, game_id=2, slot_id=7, squad_details=details)


def priced(monkeypatch, cards, now, recorded=0, mode="variants", b=None, multiplier=1, own=OWN):
    monkeypatch.setattr(oq, "load_rate_cards", lambda *a: (mode, cards))
    return oq.quote(fake_session(own, [], recorded=recorded), 41, b or booking(), console_id=3,
                    now=now, squad_multiplier=multiplier)


def test_quote_uses_rate_card_tier(hourly_models, monkeypatch):
    q = priced(monkeypatch, [card("pc", TIERED, name="PC hours")], datetime(2026, 11, 21, 22, 0))
    assert q["pricing_source"] == "rate_card" and q["gross_amount"] == 40 and q["amount"] == 40
    assert q["rate_card"] == {"name": "PC hours", "profile": "pc", "revision": 1}
    assert q["booked_minutes"] == 60 and q["players"] == 1 and q["rate_per_hour"] == 40
    for field in ("scheduled_end", "priced_until", "overtime_seconds", "rate_basis", "already_recorded",
                  "needs_end_time", "stale_after_seconds", "server_time"):
        assert field in q


def test_rate_card_subtracts_already_recorded(hourly_models, monkeypatch):
    q = priced(monkeypatch, [card("pc", TIERED)], datetime(2026, 11, 21, 22, 0), recorded=25)
    assert q["gross_amount"] == 40 and q["amount"] == 15 and q["already_recorded"] == 25


def test_falls_back_to_slot_rate_without_card_or_rule(hourly_models, monkeypatch):
    q = priced(monkeypatch, [], datetime(2026, 11, 21, 22, 0))
    assert q["pricing_source"] == "slot_rate" and q["gross_amount"] == 60 and q["rate_card"] is None
    packages = [card("r", [rule(200, 30, 30, unit=0)])]
    q = priced(monkeypatch, packages, datetime(2026, 11, 21, 22, 0))
    assert q["pricing_source"] == "slot_rate" and q["gross_amount"] == 60


def test_never_charges_more_than_old_slot_rate(hourly_models, monkeypatch):
    dear = [card("pc", [rule(90)])]  # Rs 90/h is dearer than the Rs 60 slot rate
    q = priced(monkeypatch, dear, datetime(2026, 11, 21, 22, 0))
    assert q["pricing_source"] == "slot_rate" and q["gross_amount"] == 60 and not q["amount_covers_squad"]


def test_pc_squad_compares_against_the_multiplied_old_charge(hourly_models, monkeypatch):
    per_player = [card("pc", [rule(50, each=True)])]
    q = priced(monkeypatch, per_player, datetime(2026, 11, 21, 22, 0),
               b=booking(player_count=3, enabled=True), multiplier=3)
    # Old: Rs 60 x 3 players = Rs 180. Rate card: 3 x Rs 50 = Rs 150, whole squad.
    assert q["pricing_source"] == "rate_card" and q["amount"] == 150 and q["players"] == 3
    assert q["amount_covers_squad"]


def test_stored_profile_and_game_are_used(hourly_models, monkeypatch):
    cards = [card("std", [rule(30)]), card("gta", [rule(45)], variant="GTA6")]
    q = priced(monkeypatch, cards, datetime(2026, 11, 21, 22, 0),
               b=booking(desk_pricing={"profile": "gta", "selected_game": "GTA6"}))
    assert q["rate_card"]["profile"] == "gta" and q["amount"] == 45


def test_back_to_back_bookings_count_as_booked_minutes(hourly_models, monkeypatch):
    chain = [row(4, time(19, 0), time(20, 0))]
    monkeypatch.setattr(oq, "load_rate_cards", lambda *a: ("variants", [card("pc", TIERED)]))
    q = oq.quote(fake_session(OWN, chain), 41, booking(), console_id=3, now=datetime(2026, 11, 21, 22, 0))
    # 120 booked + 60 extra = 180 min at Rs 50/h = 150; 120 booked = 100 -> extra Rs 50.
    assert q["booked_minutes"] == 120 and q["amount"] == 50


def test_large_overtime_is_now_much_lower(hourly_models, monkeypatch):
    """Five hours past a one-hour booking on a card with a cheap 181+ minute tier."""
    played_until = datetime(2026, 11, 22, 2, 0)
    monkeypatch.setattr(oq, "load_rate_cards", lambda *a: ("variants", [card("pc", TIERED)]))
    q = oq.quote(fake_session(OWN, []), 41, booking(), console_id=3,
                   now=datetime(2026, 11, 22, 2, 0), played_until=played_until)
    assert q["overtime_seconds"] == 5 * 3600
    # Slot rate would be 5h x Rs 60 = Rs 300; the card prices 6h at Rs 30/h = 180
    # minus the Rs 60 booked hour = Rs 120.
    assert q["pricing_source"] == "rate_card" and q["amount"] == 120
