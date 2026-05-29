"""Запись действий в audit log."""
from __future__ import annotations

from flask import request
from flask_login import current_user

from ..extensions import db
from ..models.audit import AuditLog


def format_status_change(old_status: str, new_status: str) -> str:
    from ..utils.i18n import order_status_label

    old_lbl, _ = order_status_label(old_status)
    new_lbl, _ = order_status_label(new_status)
    return f"{old_lbl} → {new_lbl}"


def get_entity_audit_logs(entity: str, entity_id: int, *, limit: int = 100) -> list[AuditLog]:
    return (
        AuditLog.query.filter_by(entity=entity, entity_id=entity_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


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
    if entity == "order" and entity_id:
        from datetime import datetime

        from ..models.order import Order

        order = db.session.get(Order, entity_id)
        if order:
            order.updated_at = datetime.utcnow()
