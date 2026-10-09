import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy")
    DEBUG = os.environ.get("FLASK_ENV", "development") == "development"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///edugenius_engineering.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    WTF_CSRF_TIME_LIMIT = 3600
    AI_API_KEY = os.environ.get("AI_API_KEY")
    AI_API_URL = os.environ.get("AI_API_URL", "https://api.openai.com/v1")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret"


def get_config(name=None):
    if name == "testing" or os.environ.get("FLASK_ENV") == "testing":
        return TestingConfig
    return Config
