"""Запись действий в audit log."""
from __future__ import annotations

from flask import request
from flask_login import current_user

from ..extensions import db
from ..models.audit import AuditLog


def log_audit(
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    details: str = "",
) -> None:
    user_id = None
    if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
        user_id = current_user.id
    db.session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=(details or "")[:2000],
            ip=request.remote_addr if request else None,
        )
    )
