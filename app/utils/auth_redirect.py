"""Post-login / home redirects by role."""
from urllib.parse import urlparse

from flask import request, url_for

from ..models.user import Role


def is_safe_next(target: str | None) -> bool:
    """Allow only same-host relative redirects to prevent open redirects."""
    if not target:
        return False
    ref = urlparse(target)
    # Reject absolute URLs to other hosts and protocol-relative URLs.
    if ref.scheme or ref.netloc:
        host = urlparse(request.host_url)
        return ref.scheme in ("http", "https") and ref.netloc == host.netloc
    return target.startswith("/") and not target.startswith("//")


def safe_next(target: str | None) -> str | None:
    return target if is_safe_next(target) else None


def home_endpoint_for(user) -> str:
    if user.role == Role.WORKER:
        return "worker.index"
    return "dashboard.index"


def home_url_for(user) -> str:
    return url_for(home_endpoint_for(user))
