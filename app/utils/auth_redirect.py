"""Post-login / home redirects by role."""
from flask import url_for

from ..models.user import Role


def home_endpoint_for(user) -> str:
    if user.role == Role.WORKER:
        return "worker.index"
    return "dashboard.index"


def home_url_for(user) -> str:
    return url_for(home_endpoint_for(user))
