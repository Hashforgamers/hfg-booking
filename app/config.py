# app/config.py
import os
from services.config_load import load_key_from_file

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'postgresql://postgres:postgres@db:5432/vendor_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True

    # Mail server settings
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.hashforgamers.co.in")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))  # Use 587 for TLS
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "t")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")  # Your SMTP username
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")  # Your SMTP password
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@hashforgamers.co.in")
    # Environment variables or config
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "your_key_id")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "your_key_secret")

    # Read paths from environment variables
    ENCRYPT_PRIVATE_KEY = load_key_from_file(os.getenv("ENCRYPT_PRIVATE_KEY_PATH"))
    ENCRYPT_PUBLIC_KEY = load_key_from_file(os.getenv("ENCRYPT_PUBLIC_KEY_PATH"))
    JWT_SECRET_KEY= 'dev'