"""Worker portal: assigned orders and status updates."""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...utils.i18n import translate
from ...models.settings import Settings
from ...services.inventory_consumption import sync_material_plan
from ...services.evolution_api import EvolutionAPIService
from ...services.branding import format_whatsapp_message, DEFAULT_WA_READY
from ...services.whatsapp_messages import notify_order_status_change
from ...utils.branches import effective_branch_id, filter_orders
from ...utils.decorators import worker_required
from ...utils.order_lookup import get_order_by_number as _get_order
from ...utils.worker import (
    get_current_employee,
    order_belongs_to_worker,
    worker_orders_query,
    WORKER_SETTABLE_STATUSES,
    employee_is_busy,
    employee_in_progress_order,
)
from ...services.order_assignees import (
    completed_orders_count,
    DONE_STATUSES,
    orders_with_assignees_query,
)
from ...utils.audit import log_audit, get_entity_audit_logs, format_status_change

bp = Blueprint("worker", __name__, url_prefix="/worker")

_ON = "/orders/<order_number:number>"


def _notify_ready(order: Order) -> None:
    s = Settings.get()
    if not (s.evolution_enabled and s.evolution_send_on_ready and order.client.phone):
        return
    try:
        svc = EvolutionAPIService(s)
        if svc.enabled:
            msg = format_whatsapp_message(
                s.wa_template_ready,
                s,
                default=DEFAULT_WA_READY,
                order_number=order.number,
                client_name=order.client.name,
            )
            svc.send_text(order.client.phone, msg)
    except Exception:
        current_app.logger.warning("Notification failed (worker.notify_ready)", exc_info=True)


@bp.route("/")
@login_required
@worker_required
def index():
    employee = get_current_employee()
    if not employee:
        return render_template("worker/setup.html")

    view = request.args.get("view", "active")
    status = request.args.get("status")
    branch_id = effective_branch_id(request, current_user)
    q = orders_with_assignees_query(worker_orders_query(employee))
    q = filter_orders(q, branch_id)

    if view == "history":
        q = q.filter(Order.status.in_(DONE_STATUSES))
        orders = q.order_by(
            Order.completed_at.desc().nullslast(), Order.created_at.desc()
        ).limit(200).all()
        history_count = completed_orders_count(employee.id)
        counts = {}
    else:
        if status and status in [s.value for s in OrderStatus]:
            q = q.filter(Order.status == status)
        else:
            q = q.filter(Order.status.notin_([OrderStatus.DELIVERED, OrderStatus.CANCELED]))
        orders = orders_with_assignees_query(q).order_by(
            Order.created_at.desc()
        ).limit(100).all()

        counts = {}
        base = worker_orders_query(employee).filter(
            Order.status.notin_([OrderStatus.DELIVERED, OrderStatus.CANCELED])
        )
        base = filter_orders(base, branch_id)
        counts["all"] = base.count()
        for st in WORKER_SETTABLE_STATUSES:
            counts[st.value] = base.filter(Order.status == st.value).count()
        history_count = completed_orders_count(employee.id)

    return render_template(
        "worker/orders.html",
        orders=orders,
        employee=employee,
        worker_statuses=WORKER_SETTABLE_STATUSES,
        current_status=status,
        counts=counts,
        view=view,
        history_count=history_count,
        is_busy=employee_is_busy(employee.id),
        busy_order=employee_in_progress_order(employee.id),
    )


@bp.route(_ON)
@login_required
@worker_required
def order_detail(number: str):
    employee = get_current_employee() or abort(403)
    order = _get_order(number)
    if not order_belongs_to_worker(order, employee):
        abort(403)

    return render_template(
        "worker/order_detail.html",
        order=order,
        employee=employee,
        worker_statuses=WORKER_SETTABLE_STATUSES,
        activity_logs=get_entity_audit_logs("order", order.id),
    )


@bp.post(f"{_ON}/status")
@login_required
@worker_required
def set_status(number: str):
    employee = get_current_employee() or abort(403)
    order = _get_order(number)
    if not order_belongs_to_worker(order, employee):
        abort(403)

    new_status = request.form.get("status")
    allowed = {s.value for s in WORKER_SETTABLE_STATUSES}
    if new_status not in allowed:
        flash(translate("flash.invalid_status"), "error")
        return redirect(url_for("worker.order_detail", number=number))

    if (
        new_status == OrderStatus.IN_PROGRESS
        and employee_is_busy(employee.id, exclude_order_id=order.id)
    ):
        flash(translate("worker.already_busy"), "error")
        return redirect(url_for("worker.order_detail", number=number))

    from ...services.order_work_time import sync_order_work_timer

    old_status = order.status
    order.status = new_status
    sync_order_work_timer(order, old_status, new_status)
    if new_status == OrderStatus.IN_PROGRESS and not order.started_at:
        order.started_at = datetime.utcnow()
    if new_status == OrderStatus.DONE and not order.completed_at:
        order.completed_at = datetime.utcnow()

    log_audit(
        "order.status",
        entity="order",
        entity_id=order.id,
        details=format_status_change(old_status, new_status),
    )
    db.session.commit()

    if new_status == OrderStatus.DONE and not order.inventory_consumed_at:
        sync_material_plan(order)
        flash("Укажите материалы для списания со склада", "info")
        return redirect(url_for("orders.consume_inventory", number=number))

    if new_status == OrderStatus.DONE:
        _notify_ready(order)

    try:
        notify_order_status_change(order, old_status)
    except Exception:
        current_app.logger.warning("Notification failed (worker.set_status)", exc_info=True)

    flash(translate("flash.status_updated"), "success")
    return redirect(url_for("worker.order_detail", number=number))
