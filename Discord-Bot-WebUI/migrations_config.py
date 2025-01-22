import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Disable services we don't need for migrations
    SESSION_TYPE = 'null'
    REDIS_URL = None
    CELERY_BROKER_URL = None
    CELERY_RESULT_BACKEND = None

    # Preserve Existing Tables
    SQLALCHEMY_PRESERVE_EXISTING_TABLES = True