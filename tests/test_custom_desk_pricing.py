import importlib.util
from pathlib import Path
from decimal import Decimal
import pytest

spec=importlib.util.spec_from_file_location('custom_desk_math',Path(__file__).resolve().parents[1]/'services/desk_pricing.py')
pricing=importlib.util.module_from_spec(spec);spec.loader.exec_module(pricing)

def rule(**changes):
    return dict(min_minutes=1,max_minutes=None,min_players=1,max_players=12,amount='99.50',unit_minutes=45,per_player=True,**{}) | changes

def definition(rules=None,**changes):
    return pricing.validate_definition(dict(name='Premium screen',model_name='Cafe custom model',screen_size_inches=77,game_variant='Any new game',controllers_included=True,rules=rules or [rule()]) | changes)

def test_custom_screen_players_game_and_time_units():
    result=definition()
    assert result['screen_size_inches']==77
    assert pricing.quote(result,90,6)==Decimal('1194.00')

def test_fixed_group_charge_and_per_player_session_charge():
    assert pricing.quote(definition([rule(amount='700',unit_minutes=0,per_player=False)]),600,4)==700
    assert pricing.quote(definition([rule(amount='125',unit_minutes=0)]),30,5)==625

def test_boundaries_rounding_and_gaps():
    config=definition([rule(max_minutes=180,amount='90',unit_minutes=60),rule(min_minutes=181,amount='80',unit_minutes=60)])
    assert pricing.quote(config,180,1)==270
    assert pricing.quote(config,240,1)==320
    with pytest.raises(ValueError): pricing.quote(config,180.5,1)
    assert pricing.quote(definition([rule(amount='2.51',unit_minutes=60)]),30,1)==Decimal('1.26')
    with pytest.raises(ValueError): pricing.quote(config,60,13)

@pytest.mark.parametrize('rules',[[rule(),rule()],[rule(max_minutes=180),rule(min_minutes=180)],[rule(min_players=5,max_players=3)],[rule(unit_minutes=-1)],[rule(amount='NaN')],[rule(amount=True)],[rule(amount='1.001')],[rule(per_player='yes')]])
def test_invalid_or_overlapping_rules_rejected(rules):
    with pytest.raises(ValueError): definition(rules)

def test_distinct_player_bands_can_share_time_range():
    config=definition([rule(min_players=1,max_players=2,amount='100'),rule(min_players=3,max_players=8,amount='80')])
    assert pricing.quote(config,45,3)==240

def test_existing_presets_keep_their_original_rates():
    assert pricing.quote(pricing.legacy_definition('pc',[100,90,80]),180,1)==270
    assert pricing.quote(pricing.legacy_definition('ps65',[150,125,100,100]),60,4)==400
    assert pricing.quote(pricing.legacy_definition('racing',[100,150]),30,1)==100
