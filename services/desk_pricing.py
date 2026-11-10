"""Cafe-defined desk pricing. Rule values are data, never executable formulas."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def integer(value, minimum, maximum, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try:
        number = int(value)
        if Decimal(str(value)) != number or not minimum <= number <= maximum:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return number


def validate_definition(raw):
    if not isinstance(raw, dict):
        raise ValueError("Enter a pricing model.")
    def label(key, required=False):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > 120 or (required and not value.strip()):
            raise ValueError(f"Enter {key.replace('_', ' ')} (up to 120 characters).")
        return value.strip()
    screen = raw.get("screen_size_inches")
    result = dict(name=label("name", True), model_name=label("model_name", True),
                  game_variant=label("game_variant"), screen_size_inches=None if screen in (None, "") else integer(screen, 1, 1000, "TV size"))
    if not isinstance(raw.get("controllers_included", False), bool):
        raise ValueError("Choose whether controllers are included.")
    result["controllers_included"] = raw.get("controllers_included", False)
    rules = raw.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 100:
        raise ValueError("Add between 1 and 100 price rules.")
    clean = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("Check the price rules.")
        rule = {}
        for key, low, high in (("min_minutes",1,10080),("min_players",1,1000),("max_players",1,1000),("unit_minutes",0,10080)):
            rule[key] = integer(item.get(key), low, high, key.replace('_',' '))
        maximum = item.get("max_minutes")
        rule["max_minutes"] = None if maximum in (None, "") else integer(maximum,1,10080,"Maximum minutes")
        if rule["max_minutes"] is not None and rule["max_minutes"] < rule["min_minutes"] or rule["max_players"] < rule["min_players"]:
            raise ValueError("Each range must end at or after its start.")
        try:
            if isinstance(item.get("amount"), bool):
                raise ValueError()
            amount = Decimal(str(item.get("amount")))
            if not amount.is_finite() or not 0 <= amount <= 99999999 or amount != amount.quantize(Decimal('.01')):
                raise ValueError()
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Enter a price with up to two decimal places.")
        rule["amount"] = str(amount.quantize(Decimal('.01')))
        if not isinstance(item.get("per_player"), bool):
            raise ValueError("Choose per-player or whole-group pricing.")
        rule["per_player"] = item["per_player"]
        for other in clean:
            time_overlap = rule['min_minutes'] <= (other['max_minutes'] or 10080) and other['min_minutes'] <= (rule['max_minutes'] or 10080)
            player_overlap = rule['min_players'] <= other['max_players'] and other['min_players'] <= rule['max_players']
            if time_overlap and player_overlap:
                raise ValueError("Price rules overlap. Each duration and player count must match only one rule.")
        clean.append(rule)
    result['rules'] = clean
    return result


def quote(definition, minutes, players):
    minutes = Decimal(str(minutes))
    players = integer(players,1,1000,"Players")
    matches = [r for r in definition['rules'] if Decimal(r['min_minutes']) <= minutes
               and (r['max_minutes'] is None or minutes <= Decimal(r['max_minutes']))
               and r['min_players'] <= players <= r['max_players']]
    if len(matches) != 1:
        raise ValueError("No unique rate covers this duration and player count. Choose another rate or update its rules.")
    rule = matches[0]
    total = Decimal(rule['amount']) * (players if rule['per_player'] else 1)
    if rule['unit_minutes']:
        total = total * minutes / Decimal(rule['unit_minutes'])
    return total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def legacy_definition(profile, rates):
    """Read old stored presets without changing their historic arithmetic."""
    names = {'pc':'PC duration rates','ps55':'PS5 · 55 inch','ps65':'PS5 · 65 inch',
             'gta55':'GTA6 · 55 inch','gta65':'GTA6 · 65 inch','racing':'Racing Sim'}
    if profile not in names:
        raise ValueError("This legacy rate needs a custom pricing definition.")
    def rule(amount, low=1, high=None, players_low=1, players_high=1000, unit=60, each=True):
        return dict(amount=str(amount),min_minutes=low,max_minutes=high,min_players=players_low,max_players=players_high,unit_minutes=unit,per_player=each)
    if profile == 'pc':
        rules = [rule(rates[0],1,119),rule(rates[1],120,180),rule(rates[2],181)]
    elif profile == 'racing':
        rules = [rule(rates[0],30,30,1,1,0,False),rule(rates[1],60,60,1,1,0,False)]
    else:
        rules = [rule(rate,players_low=i+1,players_high=i+1) for i,rate in enumerate(rates)]
    return validate_definition(dict(name=names[profile],model_name='Imported rates',rules=rules,
        game_variant='GTA6' if profile.startswith('gta') else '',
        screen_size_inches=int(profile[-2:]) if profile.startswith(('ps','gta')) else None,
        controllers_included=profile.startswith(('ps','gta'))))
