"""Role-based access decorators."""
from functools import wraps
from flask import abort
from flask_login import current_user

from ..models.user import Role


def role_required(*roles: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def admin_required(fn):
    return role_required(Role.ADMIN)(fn)


def staff_required(fn):
    return role_required(Role.ADMIN, Role.MANAGER, Role.WORKER)(fn)


def manager_required(fn):
    return role_required(Role.ADMIN, Role.MANAGER)(fn)


def worker_required(fn):
    return role_required(Role.WORKER)(fn)
