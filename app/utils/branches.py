"""Single-salon branch helpers."""
from __future__ import annotations

from flask import Request
from flask_login import UserMixin
from sqlalchemy.orm import Query

from ..extensions import db
from ..models.branch import Branch
from ..models.order import Order
from ..models.payment import Payment
from ..models.cash_expense import CashExpense


def get_default_branch() -> Branch:
    """Single salon branch — created on first access if missing."""
    branch = Branch.query.order_by(Branch.id).first()
    if branch is None:
        branch = Branch(name="Филиал", is_active=True)
        db.session.add(branch)
        db.session.flush()
    return branch


def get_active_branches() -> list[Branch]:
    branch = get_default_branch()
    return [branch] if branch.is_active else []


def effective_branch_id(request: Request, user: UserMixin) -> int | None:
    """No list filtering — single salon sees all records."""
    return None


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
) -> int:
    return get_default_branch().id


def branch_id_for_cabinets(
    request: Request,
    user: UserMixin,
    *,
    order_branch_id: int | None = None,
) -> int:
    if order_branch_id:
        return order_branch_id
    return get_default_branch().id
