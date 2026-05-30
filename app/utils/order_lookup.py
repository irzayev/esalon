"""Lookup and generation of public order numbers (DDMMYYNN)."""
from __future__ import annotations

import re
from datetime import datetime

from flask import abort
from flask_login import current_user

from ..models.order import Order

# Current: DDMMYYNN (e.g. 30052601). Legacy: DDMM-XXX still accepted for lookup.
ORDER_NUMBER_RE = r"(?:\d{8}|\d{4}-\d{3})"
ORDER_NUMBER_LEGACY_RE = r"\d{4}-\d{3}"


def user_can_access_order(user, order: Order) -> bool:
    """Branch-scoped access: a branch-locked user only sees their branch.

    Admins/managers without a branch (branch_id is None) can access all
    branches. Orders without a branch are visible to everyone (legacy data).
    """
    user_branch = getattr(user, "branch_id", None)
    if not user_branch:
        return True
    if order.branch_id is None:
        return True
    return order.branch_id == user_branch


def assert_order_access(order: Order) -> None:
    """Abort 403 if the current user may not access this order's branch."""
    if getattr(current_user, "is_authenticated", False) and not user_can_access_order(
        current_user, order
    ):
        abort(403)


def is_valid_order_number(number: str) -> bool:
    return bool(re.fullmatch(ORDER_NUMBER_RE, number or ""))


def get_order_by_number(number: str) -> Order:
    order = get_order_by_number_public(number)
    if not order:
        abort(404)
    assert_order_access(order)
    return order


def get_order_by_number_public(number: str) -> Order | None:
    """Lookup by public number without branch/staff access checks."""
    if not is_valid_order_number(number):
        return None
    return Order.query.filter_by(number=number).first()


def next_order_number() -> str:
    """Format: DDMMYYNN — day, month, year (2 digits), daily sequence (01–99)."""
    from ..extensions import db
    from ..services.scheduling import app_timezone

    now = datetime.now(app_timezone())
    prefix = now.strftime("%d%m%y")
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{2}})$")
    max_seq = 0
    for (number,) in db.session.query(Order.number).filter(Order.number.like(f"{prefix}%")):
        if number and (m := pattern.match(number)):
            max_seq = max(max_seq, int(m.group(1)))
    next_seq = max_seq + 1
    if next_seq > 99:
        raise ValueError(f"Daily order limit reached ({prefix}, max 99)")
    return f"{prefix}{next_seq:02d}"
