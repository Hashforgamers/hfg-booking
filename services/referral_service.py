# services/referral_service.py

import random, string
from models.voucher import Voucher
from db.extensions import db

def create_referral_voucher(user_id):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    voucher = Voucher(
        code=code,
        user_id=user_id,
        discount_percentage=100
    )
    db.session.add(voucher)
    db.session.commit()
    return voucher
