"""Lookup orders by public number (DDMM-XXX)."""
import re

from flask import abort
from flask_login import current_user

from ..models.order import Order

ORDER_NUMBER_RE = r"\d{4}-\d{3}"


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


def get_order_by_number(number: str) -> Order:
    if not re.fullmatch(ORDER_NUMBER_RE, number or ""):
        abort(404)
    order = Order.query.filter_by(number=number).first()
    if not order:
        abort(404)
    assert_order_access(order)
    return order
