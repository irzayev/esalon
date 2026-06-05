"""Detect how an order was created (staff, reservation, chatbot)."""
from __future__ import annotations

from ..models.audit import AuditLog
from ..models.order import Order

_ONLINE_CREATE_MARKERS = ("· reservation ·", "· chatbot ·")


def order_allows_client_change(order: Order) -> bool:
    """Client reassignment is allowed only for online reservation/chatbot orders."""
    if order.created_by_id is not None:
        return False
    row = (
        AuditLog.query.filter_by(
            action="order.create", entity="order", entity_id=order.id
        )
        .order_by(AuditLog.id.asc())
        .first()
    )
    if not row or not row.details:
        return False
    return any(marker in row.details for marker in _ONLINE_CREATE_MARKERS)
