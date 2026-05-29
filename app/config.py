"""Application configuration loaded from environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = STATIC_DIR / "data"
UPLOAD_DIR = STATIC_DIR / "uploads"

# Load .env from project root (no-op if missing) before reading config.
load_dotenv(PROJECT_ROOT / ".env")

# Ensure persistent dirs exist on cold start
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Insecure defaults used only in development. They are rejected in production
# by Config.validate() so they can never silently reach a live deployment.
DEFAULT_SECRET_KEY = "dev-secret-change-me"
DEFAULT_ADMIN_PASSWORD = "admin123"


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


class Config:
    # Production when FLASK_ENV=production or FLASK_DEBUG is not enabled in a
    # way that opts into dev. Default is production-safe.
    IS_PRODUCTION = os.getenv("FLASK_ENV", "production").lower() == "production"
    DEBUG = _env_bool("FLASK_DEBUG", default=False)

    SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)

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
    # Send session cookie over HTTPS only. Defaults on in production; can be
    # disabled via SESSION_COOKIE_SECURE=0 for plain-HTTP internal setups.
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@washer.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    LANGUAGES = ["ru", "az", "en"]
    DEFAULT_LANGUAGE = "ru"
    DEFAULT_CURRENCY = "AZN"

    # Токен для HTTP-cron: GET /cron/wa-reminders?token=...
    CRON_SECRET = os.getenv("CRON_SECRET", "")

    @classmethod
    def validate(cls) -> None:
        """Fail fast on insecure defaults in production deployments."""
        if not cls.IS_PRODUCTION:
            return
        errors = []
        if cls.SECRET_KEY == DEFAULT_SECRET_KEY:
            errors.append("SECRET_KEY must be set to a strong random value")
        if cls.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
            errors.append("ADMIN_PASSWORD must be changed from the default")
        if errors:
            raise RuntimeError(
                "Insecure production configuration:\n  - "
                + "\n  - ".join(errors)
                + "\nSet FLASK_ENV=development to bypass during local work."
            )
