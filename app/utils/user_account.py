"""Shared helpers for user account fields."""
from __future__ import annotations

from ..utils.client_fields import normalize_phone, validate_phone


def parse_user_phone(raw: str) -> tuple[str | None, str | None]:
    """Returns (phone, error_message). Empty phone is allowed."""
    phone = normalize_phone(raw or "")
    if not phone:
        return None, None
    ok, msg = validate_phone(phone)
    if not ok:
        return None, msg
    return phone, None
