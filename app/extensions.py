"""Flask extensions singletons."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()

login_manager.login_view = "auth.login"
login_manager.login_message = "Пожалуйста, войдите в систему"
login_manager.login_message_category = "warning"
