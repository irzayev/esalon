"""Payroll calculation helpers."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_

from ..extensions import db
from ..models.employee import Employee
from ..models.order import Order, OrderStatus
from ..models.order_assignment import OrderAssignment
from ..utils.branches import filter_orders


def parse_period(from_raw: str | None, to_raw: str | None) -> tuple[date, date]:
    today = date.today()
    start_default = today.replace(day=1)
    next_month = (start_default + timedelta(days=32)).replace(day=1)
    end_default = next_month - timedelta(days=1)
    try:
        period_start = datetime.strptime(from_raw, "%Y-%m-%d").date() if from_raw else start_default
    except ValueError:
        period_start = start_default
    try:
        period_end = datetime.strptime(to_raw, "%Y-%m-%d").date() if to_raw else end_default
    except ValueError:
        period_end = end_default
    if period_end < period_start:
        period_end = period_start
    return period_start, period_end


def build_payroll_row(
    emp: Employee,
    period_start: date,
    period_end: date,
    branch_id: int | None = None,
) -> dict:
    done_statuses = [OrderStatus.DONE]
    assigned_order_ids = db.session.query(OrderAssignment.order_id).filter(
        OrderAssignment.employee_id == emp.id
    )
    q = Order.query.filter(
        db.or_(Order.id.in_(assigned_order_ids), Order.assigned_to_id == emp.id),
        Order.status.in_(done_statuses),
        and_(
            db.func.date(Order.completed_at) >= period_start,
            db.func.date(Order.completed_at) <= period_end,
        ),
    )
    orders = filter_orders(q, branch_id).distinct().all()

    visits_count = len(orders)
    revenue_total = round(sum(o.final_total or 0 for o in orders), 2)
    base = float(emp.base_salary or 0)
    bonus = 0.0
    note = ""

    if emp.salary_model == "fixed":
        note = "Фиксированная ставка"
    elif emp.salary_model == "percent":
        bonus = revenue_total * (float(emp.percent or 0) / 100)
        note = f"Процент от выручки: {emp.percent}%"
    elif emp.salary_model == "kpi":
        cars_bonus = visits_count * float(emp.kpi_bonus_per_visit or 0)
        revenue_bonus = 0.0
        if revenue_total >= float(emp.kpi_target_revenue or 0):
            revenue_bonus = revenue_total * (float(emp.kpi_bonus_revenue_percent or 0) / 100)
        bonus = cars_bonus + revenue_bonus
        note = (
            f"KPI: cars>={emp.kpi_target_visits}, rev>={emp.kpi_target_revenue:.2f}; "
            f"cars_bonus={cars_bonus:.2f}, rev_bonus={revenue_bonus:.2f}"
        )

    total = round(base + bonus, 2)
    cars_target = max(int(emp.kpi_target_visits or 0), 1)
    rev_target = max(float(emp.kpi_target_revenue or 0), 1.0)
    cars_progress = min(visits_count / cars_target, 1.0) * 100
    rev_progress = min(revenue_total / rev_target, 1.0) * 100
    kpi_score = round((cars_progress + rev_progress) / 2, 1)

    return {
        "employee": emp,
        "visits_count": visits_count,
        "revenue_total": revenue_total,
        "base": round(base, 2),
        "bonus": round(bonus, 2),
        "total": total,
        "kpi_score": kpi_score,
        "note": note,
    }


def payroll_rows_for_period(
    period_start: date,
    period_end: date,
    branch_id: int | None = None,
) -> list[dict]:
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    return [build_payroll_row(emp, period_start, period_end, branch_id) for emp in employees]
