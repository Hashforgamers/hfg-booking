# utils/common.py
import random
import string
from flask import current_app

RAZORPAY_KEY_ID = None
RAZORPAY_KEY_SECRET = None

def get_razorpay_keys():
    from flask import current_app
    return (current_app.config.get("RAZORPAY_KEY_ID"),
            current_app.config.get("RAZORPAY_KEY_SECRET"))

def generate_fid(length=16):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_access_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
