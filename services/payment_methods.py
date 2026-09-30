from db.extensions import db
"""Canonical cafe payment acceptance. Shared contract with the dashboard service."""
from sqlalchemy import text

ALIASES = {
    'hash_wallet': {'hash wallet', 'wallet', 'global wallet', 'hash global wallet'},
    'cafe_wallet': {'cafe wallet', 'cafe specific wallet'},
    'hash_global_pass': {'hash global pass', 'global pass', 'hash pass', 'hash'},
    'cafe_specific_pass': {'cafe specific pass', 'cafe pass', 'vendor pass'},
    'payment_gateway': {'payment gateway', 'gateway', 'online'},
    'pay_at_cafe': {'pay at cafe', 'pay in cafe', 'cash'},
}

def canonical_method(value):
    clean = str(value or '').lower().strip().replace('_', ' ').replace('-', ' ')
    return next((key for key, names in ALIASES.items() if clean == key.replace('_', ' ') or clean in names), None)


def accepted_methods(vendor_id):
    rows = db.session.execute(text('''SELECT pm.method_name FROM payment_vendor_map vm
        JOIN payment_method pm ON pm.pay_method_id=vm.pay_method_id WHERE vm.vendor_id=:vid'''),
        {'vid': vendor_id}).scalars().all()
    return {name for row in rows if (name := canonical_method(row))}


def require_method(vendor_id, method):
    if method not in accepted_methods(vendor_id):
        raise ValueError(f'{method} is disabled at this cafe')
