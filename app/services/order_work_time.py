"""In-progress work time (minutes only): live while status is İşlənir, pauses excluded."""
from __future__ import annotations

from datetime import datetime

from ..models.order import Order, OrderStatus


def _elapsed_minutes(since: datetime, now: datetime) -> int:
    return max(0, int((now - since).total_seconds()) // 60)


def sync_order_work_timer(
    order: Order,
    old_status: str,
    new_status: str,
    *,
    now: datetime | None = None,
) -> None:
    """Call after ``order.status`` is updated."""
    now = now or datetime.utcnow()

    if old_status == OrderStatus.IN_PROGRESS:
        since = order.in_progress_since
        if since:
            order.in_progress_minutes = (order.in_progress_minutes or 0) + _elapsed_minutes(
                since, now
            )
        order.in_progress_since = None

    if new_status == OrderStatus.IN_PROGRESS:
        order.in_progress_since = now


def order_work_minutes(order: Order, *, now: datetime | None = None) -> int | None:
    """Total minutes in progress (pauses excluded). ``None`` when canceled (show «—»)."""
    if order.status == OrderStatus.CANCELED:
        return None

    now = now or datetime.utcnow()
    total = int(order.in_progress_minutes or 0)

    if order.status == OrderStatus.IN_PROGRESS:
        since = order.in_progress_since or order.started_at
        if since:
            total += _elapsed_minutes(since, now)

    return total


def batch_order_work_minutes(
    orders: list[Order],
    *,
    now: datetime | None = None,
) -> dict[int, int | None]:
    now = now or datetime.utcnow()
    return {o.id: order_work_minutes(o, now=now) for o in orders}
