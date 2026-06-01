"""Helpers for worker portal (user ↔ employee profile)."""
from __future__ import annotations

from flask_login import current_user

from ..models.employee import Employee
from ..models.order import Order, OrderStatus
from ..models.user import Role
from ..services.order_assignees import order_has_assignee, orders_for_employee_query

# Статусы, которые работник может выставить сам (İşlənir / Gözləyir / Hazırdı)
WORKER_SETTABLE_STATUSES = (
    OrderStatus.IN_PROGRESS,
    OrderStatus.WAITING,
    OrderStatus.DONE,
)


def get_current_employee() -> Employee | None:
    if not getattr(current_user, "is_authenticated", False) or not current_user.is_authenticated:
        return None
    if current_user.role != Role.WORKER:
        return None
    return Employee.query.filter_by(user_id=current_user.id, is_active=True).first()


def order_belongs_to_worker(order: Order, employee: Employee | None = None) -> bool:
    emp = employee or get_current_employee()
    if not emp:
        return False
    return order_has_assignee(order, emp.id)


def worker_orders_query(employee: Employee):
    return orders_for_employee_query(employee.id)


def employee_in_progress_order(
    employee_id: int,
    *,
    exclude_order_id: int | None = None,
) -> Order | None:
    """Заказ в работе (İşlənir) у сотрудника, если есть."""
    q = orders_for_employee_query(employee_id).filter(
        Order.status == OrderStatus.IN_PROGRESS
    )
    if exclude_order_id:
        q = q.filter(Order.id != exclude_order_id)
    return q.order_by(Order.started_at.desc().nullslast()).first()


def employee_is_busy(employee_id: int, *, exclude_order_id: int | None = None) -> bool:
    return employee_in_progress_order(employee_id, exclude_order_id=exclude_order_id) is not None
