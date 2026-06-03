"""Order executor assignment helpers."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Query, joinedload

from ..extensions import db
from ..models.employee import Employee
from ..models.order import Order, OrderStatus
from ..models.order_assignment import OrderAssignment

DONE_STATUSES = (OrderStatus.DONE, OrderStatus.DELIVERED)


def get_assigned_employee_ids(order: Order) -> list[int]:
    if order.assignments:
        return [a.employee_id for a in order.assignments]
    if order.assigned_to_id:
        return [order.assigned_to_id]
    return []


def get_assignees(order: Order) -> list[Employee]:
    if order.assignments:
        return [a.employee for a in order.assignments if a.employee]
    if order.assignee:
        return [order.assignee]
    return []


def assignee_names(order: Order) -> str:
    names = [e.name for e in get_assignees(order) if e and e.name]
    return ", ".join(names) if names else "—"


def sync_order_assignees(order: Order, employee_ids: list[int]) -> None:
    """Replace executors on order; keeps assigned_to_id as first assignee."""
    unique_ids: list[int] = []
    seen: set[int] = set()
    for eid in employee_ids:
        if eid and eid not in seen:
            seen.add(eid)
            unique_ids.append(eid)

    valid = {
        e.id
        for e in Employee.query.filter(
            Employee.id.in_(unique_ids), Employee.is_active.is_(True)
        ).all()
    } if unique_ids else set()
    unique_ids = [eid for eid in unique_ids if eid in valid]

    current = {a.employee_id: a for a in list(order.assignments)}
    for eid in unique_ids:
        if eid not in current:
            db.session.add(OrderAssignment(order_id=order.id, employee_id=eid))
    for eid, row in current.items():
        if eid not in unique_ids:
            db.session.delete(row)

    order.assigned_to_id = unique_ids[0] if unique_ids else None


def add_order_assignee(order: Order, employee_id: int) -> None:
    """Add executor without removing existing assignees."""
    if not employee_id:
        return
    ids = get_assigned_employee_ids(order)
    if employee_id not in ids:
        ids.append(employee_id)
    sync_order_assignees(order, ids)


def order_has_assignee(order: Order, employee_id: int) -> bool:
    if not employee_id:
        return False
    if any(a.employee_id == employee_id for a in order.assignments):
        return True
    return order.assigned_to_id == employee_id


def orders_for_employee_query(employee_id: int) -> Query:
    """Orders where employee is listed as executor."""
    subq = db.session.query(OrderAssignment.order_id).filter(
        OrderAssignment.employee_id == employee_id
    )
    return Order.query.filter(
        or_(Order.id.in_(subq), Order.assigned_to_id == employee_id)
    )


def completed_orders_for_employee(
    employee_id: int,
    *,
    limit: int | None = None,
) -> list[Order]:
    q = (
        orders_for_employee_query(employee_id)
        .filter(Order.status.in_(DONE_STATUSES))
        .order_by(Order.completed_at.desc().nullslast(), Order.created_at.desc())
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def completed_orders_count(employee_id: int) -> int:
    return (
        orders_for_employee_query(employee_id)
        .filter(Order.status.in_(DONE_STATUSES))
        .count()
    )


def orders_with_assignees_query(base: Query | None = None) -> Query:
    q = base if base is not None else Order.query
    return q.options(
        joinedload(Order.assignments).joinedload(OrderAssignment.employee),
        joinedload(Order.assignee),
    )
