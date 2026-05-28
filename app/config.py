"""Application configuration loaded from environment."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = STATIC_DIR / "data"
UPLOAD_DIR = STATIC_DIR / "uploads"

# Ensure persistent dirs exist on cold start
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(UPLOAD_DIR))
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@washer.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

    LANGUAGES = ["ru", "az", "en"]
    DEFAULT_LANGUAGE = "ru"
    DEFAULT_CURRENCY = "AZN"

    # Токен для HTTP-cron: GET /cron/wa-reminders?token=...
    CRON_SECRET = os.getenv("CRON_SECRET", "")
