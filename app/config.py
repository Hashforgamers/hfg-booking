# app/config.py

import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'postgresql://postgres:postgres@db:5432/vendor_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = True
