"""Multi-branch filtering for lists and reports."""
from __future__ import annotations

from flask import Request
from flask_login import UserMixin
from sqlalchemy.orm import Query

from ..extensions import db
from ..models.branch import Branch
from ..models.order import Order
from ..models.payment import Payment
from ..models.cash_expense import CashExpense


def get_active_branches() -> list[Branch]:
    return Branch.query.filter_by(is_active=True).order_by(Branch.name).all()


def multi_branch_enabled() -> bool:
    return len(get_active_branches()) > 1


def parse_branch_arg(request: Request) -> int | None:
    raw = request.args.get("branch_id") or request.form.get("branch_id")
    if not raw:
        return None
    try:
        bid = int(raw)
    except (TypeError, ValueError):
        return None
    if Branch.query.filter_by(id=bid, is_active=True).first():
        return bid
    return None


def effective_branch_id(request: Request, user: UserMixin) -> int | None:
    """Selected branch for queries. None = all branches (admins/managers only)."""
    if getattr(user, "branch_id", None):
        return user.branch_id
    return parse_branch_arg(request)


def branch_filter_context(request: Request, user: UserMixin) -> dict:
    branches = get_active_branches()
    locked = bool(getattr(user, "branch_id", None))
    bid = effective_branch_id(request, user)
    current_branch = db.session.get(Branch, bid) if bid else None
    return {
        "branches": branches,
        "show_branch_filter": len(branches) > 1 and not locked,
        "current_branch_id": bid,
        "current_branch": current_branch,
        "user_branch_locked": locked,
    }


def filter_orders(q: Query, branch_id: int | None) -> Query:
    if branch_id is not None:
        q = q.filter(Order.branch_id == branch_id)
    return q


def filter_payments(q: Query, branch_id: int | None) -> Query:
    if branch_id is not None:
        q = q.join(Order, Payment.order_id == Order.id).filter(Order.branch_id == branch_id)
    return q


def filter_cash_expenses(q: Query, branch_id: int | None) -> Query:
    if branch_id is not None:
        q = q.filter(CashExpense.branch_id == branch_id)
    return q


def resolve_order_branch_id(
    request: Request,
    user: UserMixin,
    *,
    form_value: str | None = None,
) -> int | None:
    """Branch for a newly created order."""
    if getattr(user, "branch_id", None):
        return user.branch_id
    if form_value:
        try:
            bid = int(form_value)
            if Branch.query.filter_by(id=bid, is_active=True).first():
                return bid
        except (TypeError, ValueError):
            pass
    bid = effective_branch_id(request, user)
    if bid is not None:
        return bid
    active = get_active_branches()
    if len(active) == 1:
        return active[0].id
    return None


def branch_id_for_cabinets(
    request: Request,
    user: UserMixin,
    *,
    order_branch_id: int | None = None,
) -> int | None:
    """Branch used to load bay lists (orders, schedule, dashboard).

    Unlike effective_branch_id, falls back to the only active branch or the first
    one so admins without a branch filter still see configured bays.
    """
    if order_branch_id:
        return order_branch_id
    if getattr(user, "branch_id", None):
        return user.branch_id
    bid = parse_branch_arg(request)
    if bid is not None:
        return bid
    active = get_active_branches()
    if len(active) == 1:
        return active[0].id
    if active:
        return active[0].id
    return None
