"""Stored work time (minutes) for completed orders."""
from __future__ import annotations

from datetime import datetime

from ..models.order import Order, OrderStatus


def sync_order_work_timer(
    order: Order,
    old_status: str,
    new_status: str,
    *,
    now: datetime | None = None,
) -> None:
    """No-op: live in-progress timer removed with simplified statuses."""


def order_work_minutes(order: Order, *, now: datetime | None = None) -> int | None:
    """Stored minutes when available. ``None`` when canceled (show «—»)."""
    if order.status == OrderStatus.CANCELED:
        return None
    stored = int(order.in_progress_minutes or 0)
    return stored if stored > 0 else None


def batch_order_work_minutes(
    orders: list[Order],
    *,
    now: datetime | None = None,
) -> dict[int, int | None]:
    return {o.id: order_work_minutes(o, now=now) for o in orders}
