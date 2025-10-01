import os
from services.config_load import load_key_from_file

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev")
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URI",
        "postgresql://postgres:postgres@db:5432/vendor_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 5,
        "max_overflow": 10,
    }

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.hashforgamers.co.in")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "t")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@hashforgamers.co.in")

    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "your_key_id")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "your_key_secret")

    ENCRYPT_PRIVATE_KEY = load_key_from_file(os.getenv("ENCRYPT_PRIVATE_KEY_PATH", ""))
    ENCRYPT_PUBLIC_KEY = load_key_from_file(os.getenv("ENCRYPT_PUBLIC_KEY_PATH", ""))
