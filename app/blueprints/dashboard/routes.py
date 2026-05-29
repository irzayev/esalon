from calendar import monthrange
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from sqlalchemy import func

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.client import Client
from ...models.payment import Payment, PaymentStatus
from ...models.inventory import InventoryItem
from ...models.user import Role
from ...services.report_queries import compute_period_pnl
from ...utils.branches import effective_branch_id, filter_orders, filter_payments
from ...services.scheduling import schedule_events, app_timezone, local_to_utc_start

bp = Blueprint("dashboard", __name__)

_MONTHS_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def _current_month_bounds(today):
    """Первый и последний день текущего календарного месяца (UTC date)."""
    month_start = today.replace(day=1)
    last_day = monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)
    return month_start, month_end


def _month_daily_stats(today, branch_id: int | None):
    """Выручка и число заказов по каждому дню текущего месяца."""
    month_start, month_end = _current_month_bounds(today)
    last_day = month_end.day
    days = []
    for day in range(1, last_day + 1):
        d = today.replace(day=day)
        rev_q = (
            db.session.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.status == PaymentStatus.SUCCESS)
            .filter(func.date(Payment.created_at) == d)
        )
        rev_q = filter_payments(rev_q, branch_id)
        revenue = rev_q.scalar()
        ord_q = db.session.query(func.count(Order.id)).filter(func.date(Order.created_at) == d)
        ord_q = filter_orders(ord_q, branch_id)
        orders_count = ord_q.scalar()
        days.append({
            "date": d.strftime("%d.%m"),
            "revenue": float(revenue or 0),
            "orders": int(orders_count or 0),
        })
    return days, month_start, month_end


@bp.route("/dashboard")
@login_required
def index():
    if current_user.role == Role.WORKER:
        return redirect(url_for("worker.index"))

    today = datetime.utcnow().date()
    branch_id = effective_branch_id(request, current_user)

    rev_today_q = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.status == PaymentStatus.SUCCESS)
        .filter(func.date(Payment.created_at) == today)
    )
    revenue_today = filter_payments(rev_today_q, branch_id).scalar()

    active_q = Order.query.filter(
        Order.status.in_([OrderStatus.NEW, OrderStatus.BOOKED, OrderStatus.IN_PROGRESS, OrderStatus.WAITING])
    )
    active_orders = filter_orders(active_q, branch_id).count()
    total_clients = Client.query.count()

    low_stock = InventoryItem.query.filter(InventoryItem.qty <= InventoryItem.min_qty).all()
    recent_q = Order.query.order_by(Order.created_at.desc())
    recent_orders = filter_orders(recent_q, branch_id).limit(8).all()

    month_days, month_start, month_end = _month_daily_stats(today, branch_id)
    revenue_month = sum(d["revenue"] for d in month_days)
    pnl = compute_period_pnl(month_start, month_end, branch_id)
    net_income_month = pnl["net_income"]
    chart_month_label = f"{_MONTHS_RU[today.month - 1].capitalize()} {today.year}"
    chart_period_label = f"{month_start.strftime('%d.%m')} — {month_end.strftime('%d.%m.%Y')}"

    tz = app_timezone()
    today_local = datetime.now(tz).replace(tzinfo=None)
    day_start = local_to_utc_start(today_local)
    day_end = local_to_utc_start(today_local + timedelta(days=1))
    schedule_today = schedule_events(branch_id, day_start, day_end, resource="bay")

    return render_template(
        "dashboard/index.html",
        revenue_today=revenue_today,
        revenue_month=revenue_month,
        net_income_month=net_income_month,
        pnl=pnl,
        active_orders=active_orders,
        total_clients=total_clients,
        low_stock=low_stock,
        recent_orders=recent_orders,
        month_days=month_days,
        chart_month_label=chart_month_label,
        chart_period_label=chart_period_label,
        schedule_today=schedule_today,
    )
