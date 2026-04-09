import os
from services.config_load import load_key_from_file

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    DEBUG = os.getenv("DEBUG_MODE", "false").lower() == "true"

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URI",
        "postgresql://postgres:postgres@db:5432/vendor_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SEC", "1800")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT_SEC", "30")),
    }
    SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"

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

    # Optional platform fee (app fee) defaults to 0
    APP_FEE_PERCENT = float(os.getenv("APP_FEE_PERCENT", "2") or 0)
    APP_FEE_FLAT = float(os.getenv("APP_FEE_FLAT", "0") or 0)

    # Optional pricing audit logging (guarded to avoid noisy prod logs)
    LOG_BOOKING_PRICING = os.getenv("LOG_BOOKING_PRICING", "false").lower() in ("true", "1", "t", "yes", "y")

    # App cancellation policy (defaults tuned for low-noise app operations)
    CANCELLATION_FEE_ENABLED = os.getenv("CANCELLATION_FEE_ENABLED", "true").lower() in ("true", "1", "t", "yes", "y")
    CANCELLATION_FEE_PERCENT = float(os.getenv("CANCELLATION_FEE_PERCENT", "5") or 0)
    CANCELLATION_FEE_FLAT = float(os.getenv("CANCELLATION_FEE_FLAT", "0") or 0)
    CANCELLATION_FEE_MIN = float(os.getenv("CANCELLATION_FEE_MIN", "0") or 0)
    CANCELLATION_FEE_MAX = float(os.getenv("CANCELLATION_FEE_MAX", "50") or 0)
    CANCELLATION_FREE_BEFORE_MINUTES = int(os.getenv("CANCELLATION_FREE_BEFORE_MINUTES", "180") or 180)
    CANCELLATION_FEE_APPLY_ON_PAY_AT_CAFE = os.getenv("CANCELLATION_FEE_APPLY_ON_PAY_AT_CAFE", "false").lower() in ("true", "1", "t", "yes", "y")
    CANCELLATION_FEE_APPLY_ON_PASS = os.getenv("CANCELLATION_FEE_APPLY_ON_PASS", "false").lower() in ("true", "1", "t", "yes", "y")

    # No-show policy (default: full fee on paid bookings, waive pending pay-at-cafe)
    NO_SHOW_FEE_ENABLED = os.getenv("NO_SHOW_FEE_ENABLED", "true").lower() in ("true", "1", "t", "yes", "y")
    NO_SHOW_FEE_PERCENT = float(os.getenv("NO_SHOW_FEE_PERCENT", "100") or 0)
    NO_SHOW_FEE_FLAT = float(os.getenv("NO_SHOW_FEE_FLAT", "0") or 0)
    NO_SHOW_FEE_MIN = float(os.getenv("NO_SHOW_FEE_MIN", "0") or 0)
    NO_SHOW_FEE_MAX = float(os.getenv("NO_SHOW_FEE_MAX", "100000") or 0)
    NO_SHOW_FEE_APPLY_ON_PAY_AT_CAFE = os.getenv("NO_SHOW_FEE_APPLY_ON_PAY_AT_CAFE", "false").lower() in ("true", "1", "t", "yes", "y")
    NO_SHOW_FEE_APPLY_ON_PASS = os.getenv("NO_SHOW_FEE_APPLY_ON_PASS", "true").lower() in ("true", "1", "t", "yes", "y")

    # Public URLs for email action links
    BOOKING_PUBLIC_BASE_URL = os.getenv("BOOKING_PUBLIC_BASE_URL", "").strip()
    DASHBOARD_PUBLIC_URL = os.getenv("DASHBOARD_PUBLIC_URL", "https://dashboard.hashforgamers.com").strip()

    # Pay-at-cafe email action token settings
    PAY_AT_CAFE_EMAIL_ACTION_SECRET = os.getenv("PAY_AT_CAFE_EMAIL_ACTION_SECRET", SECRET_KEY)
    PAY_AT_CAFE_EMAIL_ACTION_TTL_MINUTES = int(os.getenv("PAY_AT_CAFE_EMAIL_ACTION_TTL_MINUTES", "720") or 720)

    # API performance / observability knobs
    API_ENABLE_TIMING_HEADERS = os.getenv("API_ENABLE_TIMING_HEADERS", "true").lower() in ("true", "1", "t", "yes", "y")
    API_SLOW_REQUEST_MS = int(os.getenv("API_SLOW_REQUEST_MS", "120") or 120)
    API_PUBLIC_CACHE_CONTROL = os.getenv("API_PUBLIC_CACHE_CONTROL", "public, max-age=15, stale-while-revalidate=30")
    API_PRIVATE_CACHE_CONTROL = os.getenv("API_PRIVATE_CACHE_CONTROL", "no-store")

    # Endpoint-level read microcache profiles
    READ_MICROCACHE_MAX_ITEMS = int(os.getenv("READ_MICROCACHE_MAX_ITEMS", "25000") or 25000)
    BOOKING_PRICING_ESTIMATE_CACHE_TTL_SEC = int(os.getenv("BOOKING_PRICING_ESTIMATE_CACHE_TTL_SEC", "10") or 10)
    USER_BOOKINGS_CACHE_TTL_SEC = int(os.getenv("USER_BOOKINGS_CACHE_TTL_SEC", "8") or 8)

    # Auth performance + logging controls
    AUTH_DEBUG_LOGS = os.getenv("AUTH_DEBUG_LOGS", "false").lower() in ("true", "1", "t", "yes", "y")
    AUTH_DECRYPT_CACHE_TTL_SEC = int(os.getenv("AUTH_DECRYPT_CACHE_TTL_SEC", "300") or 300)

    # Bound user bookings payload size for consistent latency
    USER_BOOKINGS_MAX_ITEMS = int(os.getenv("USER_BOOKINGS_MAX_ITEMS", "120") or 120)
