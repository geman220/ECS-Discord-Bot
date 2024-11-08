# web_config.py
from datetime import timedelta, datetime
import os
import redis
import pytz

class Config:
    # Basic Flask/App Configuration
    SECRET_KEY = os.getenv('SECRET_KEY')
    MATCH_CHANNEL_ID = os.getenv('MATCH_CHANNEL_ID')

    # Add secure cookie settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True

    # Ensures that generated URLs use https
    PREFERRED_URL_SCHEME = 'https'
    
    # Database Configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = 10
    SQLALCHEMY_POOL_TIMEOUT = 30

    # Database monitoring settings
    DB_CONNECTION_TIMEOUT = 30
    DB_MONITOR_ENABLED = True
    
    # External Service Configuration
    WOO_CONSUMER_KEY = os.getenv('WC_KEY')
    WOO_CONSUMER_SECRET = os.getenv('WC_SECRET')
    SERVER_ID = os.getenv('SERVER_ID')
    WOO_API_URL = os.getenv('WOO_API_URL')
    DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
    DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
    TEAM_ID = os.getenv('TEAM_ID')
    BOT_API_URL = os.getenv('BOT_API_URL')
    
    # Timezone Settings
    timezone = 'America/Los_Angeles'
    TIMEZONE = pytz.timezone('America/Los_Angeles')
    
    # Redis Session Configuration
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=8)
    SESSION_USE_SIGNER = True
    SESSION_REDIS = redis.from_url('redis://redis:6379')
    SESSION_KEY_PREFIX = 'flask_session:'
    
    # JWT Configuration
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    
    # External Service Keys
    TWILIO_SID = os.getenv('TWILIO_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    TEXTMAGIC_USERNAME = os.getenv('TEXTMAGIC_USERNAME')
    TEXTMAGIC_API_KEY = os.getenv('TEXTMAGIC_API_KEY')

    @staticmethod
    def get_current_time():
        """Helper method to get current time in PST"""
        return datetime.now(pytz.timezone('America/Los_Angeles'))