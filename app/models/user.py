from datetime import datetime
from enum import StrEnum

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..utils.client_fields import normalize_phone


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    WORKER = "worker"
    CLIENT = "client"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, index=True)
    name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=Role.WORKER)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    avatar = db.Column(db.String(255))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship("Branch", backref="users")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @classmethod
    def find_by_login(cls, identifier: str) -> "User | None":
        """Поиск по email или телефону (+994…)."""
        ident = (identifier or "").strip()
        if not ident:
            return None
        if "@" in ident:
            return cls.query.filter_by(email=ident.lower()).first()
        phone = normalize_phone(ident)
        if phone:
            return cls.query.filter_by(phone=phone).first()
        return None

    @property
    def login_label(self) -> str:
        if self.phone:
            return self.phone
        return self.email

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role == Role.MANAGER

    def __repr__(self) -> str:
        return f"<User {self.email} {self.role}>"
