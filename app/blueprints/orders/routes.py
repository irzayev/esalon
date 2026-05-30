"""Orders: list / create / view / status / payments / photos."""
import re
from datetime import datetime, timedelta
from pathlib import Path
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    jsonify, send_file, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from ...extensions import db
from ...models.order import Order, OrderItem, OrderStatus, OrderPhoto
from ...models.client import Client, Car
from ...models.service import Service, ServicePackage, matches_car_body_type
from ...models.order_material import OrderMaterialPlan
from ...models.inventory import InventoryMovement, InventoryItem
from ...services.inventory_consumption import (
    sync_material_plan,
    apply_material_consumption,
    apply_consumption_adjustment,
    get_applied_quantities_from_movements,
    ensure_plans_from_movements,
    order_has_material_lines,
    add_plan_line,
    remove_plan_line,
    save_plan_draft,
)
from ...models.payment import Payment, PaymentMethod, PaymentStatus
from ...models.bonus import BonusWallet, BonusTransaction, BonusType
from ...models.settings import Settings
from ...models.employee import Employee
from ...models.audit import AuditLog
from ...utils.audit import log_audit, get_entity_audit_logs, format_status_change
from ...utils.branches import (
    effective_branch_id,
    filter_orders,
    get_active_branches,
    multi_branch_enabled,
    resolve_order_branch_id,
    branch_id_for_bays,
)
from ...utils.order_lookup import get_order_by_number as _get_order, assert_order_access, next_order_number
from ...utils.decorators import staff_required, manager_required
from ...utils.uploads import save_upload, ALLOWED_IMAGE
from ...services.evolution_api import EvolutionAPIService
from ...services.branding import (
    format_whatsapp_message,
    DEFAULT_WA_READY,
    DEFAULT_WA_BOOKING,
    DEFAULT_WA_PAYMENT,
)
from ...services.whatsapp_messages import notify_order_status_change
from ...services.receipt import render_receipt_html, _payment_totals
from ...services.order_assignees import (
    sync_order_assignees,
    get_assigned_employee_ids,
    orders_with_assignees_query,
)
from ...models.bay import Bay
from ...services.scheduling import (
    parse_schedule_datetime,
    apply_order_schedule,
    occupy_bay_now,
    active_bays_for_branch,
    order_slot_bounds,
    utc_naive_to_local,
    order_duration_minutes,
    order_scheduled_duration_minutes,
    DEFAULT_SLOT_MINUTES,
)

bp = Blueprint("orders", __name__)

_ON = "/<order_number:number>"


def _log_notify_failure(context: str) -> None:
    """Best-effort notifications must not break the request, but failures
    should be logged rather than silently swallowed."""
    current_app.logger.warning("Notification failed (%s)", context, exc_info=True)


def _notify_client_whatsapp(order: Order, template: str, *, default: str) -> None:
    s = Settings.get()
    if not (s.evolution_enabled and order.client.phone):
        return
    svc = EvolutionAPIService(s)
    if not svc.enabled:
        return
    msg = format_whatsapp_message(
        template,
        s,
        default=default,
        order_number=order.number,
        client_name=order.client.name,
    )
    svc.send_text(order.client.phone, msg)


@bp.route("/")
@login_required
@staff_required
def index():
    status = request.args.get("status")
    branch_id = effective_branch_id(request, current_user)
    q = Order.query
    q = filter_orders(q, branch_id)
    if status:
        q = q.filter(Order.status == status)
    orders = (
        orders_with_assignees_query(q)
        .order_by(Order.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "orders/index.html",
        orders=orders,
        current_status=status,
        show_branch_column=multi_branch_enabled(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@staff_required
def new():
    if request.method == "POST":
        try:
            client_id = int(request.form.get("client_id") or 0)
        except (TypeError, ValueError):
            abort(400)
        client = db.session.get(Client, client_id) or abort(400)
        car_id = request.form.get("car_id")
        initial_status = OrderStatus.NEW.value
        order = Order(
            client_id=client.id,
            car_id=int(car_id) if car_id else None,
            branch_id=resolve_order_branch_id(
                request, current_user, form_value=request.form.get("branch_id")
            ),
            created_by_id=current_user.id,
            status=initial_status,
            notes=request.form.get("notes", ""),
        )
        try:
            order.number = next_order_number()
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("orders.new"))
        db.session.add(order)
        db.session.flush()

        if request.form.get("book_appointment"):
            scheduled_at = parse_schedule_datetime(
                request.form.get("schedule_date"),
                request.form.get("schedule_time"),
            )
            if not scheduled_at:
                flash("Укажите дату и время записи", "error")
                db.session.rollback()
                return redirect(url_for("orders.new"))
            duration = int(request.form.get("schedule_duration") or DEFAULT_SLOT_MINUTES)
            bay_id = request.form.get("bay_id")
            if not bay_id:
                flash("Выберите бокс", "error")
                db.session.rollback()
                return redirect(url_for("orders.new"))
            err = apply_order_schedule(
                order,
                bay_id=int(bay_id),
                scheduled_at=scheduled_at,
                duration_min=duration,
                set_booked=True,
            )
            if err:
                flash(err, "error")
                db.session.rollback()
                return redirect(url_for("orders.new"))

        car_label = order.car.display if order.car else "без авто"
        log_audit(
            "order.create",
            entity="order",
            entity_id=order.id,
            details=f"#{order.number} · {client.name} ({client.phone}) · {car_label}",
        )
        try:
            db.session.commit()
        except IntegrityError:
            # Two concurrent creates can collide on the unique order number.
            db.session.rollback()
            flash("Не удалось создать заказ из-за конфликта номеров. Повторите.", "error")
            return redirect(url_for("orders.new"))
        _recalc_total(order)

        s = Settings.get()
        if s.evolution_send_on_booking:
            try:
                _notify_client_whatsapp(order, s.wa_template_booking, default=DEFAULT_WA_BOOKING)
            except Exception:
                _log_notify_failure("order.new booking")
        try:
            notify_order_status_change(order, initial_status)
        except Exception:
            _log_notify_failure("order.new status")

        return redirect(url_for("orders.detail", number=order.number))

    clients = Client.query.order_by(Client.name).all()
    branches = get_active_branches()
    default_branch_id = resolve_order_branch_id(request, current_user)
    if default_branch_id is None and branches:
        default_branch_id = branches[0].id
    branch_id = branch_id_for_bays(request, current_user, order_branch_id=default_branch_id)
    bays = active_bays_for_branch(branch_id) if branch_id else []
    from datetime import datetime as dt
    from ...services.scheduling import app_timezone
    today = dt.now(app_timezone()).strftime("%Y-%m-%d")
    return render_template(
        "orders/new.html",
        clients=clients,
        branches=branches,
        bays=bays,
        schedule_today=today,
        show_branch_select=len(branches) > 1 and not current_user.branch_id,
        default_branch_id=default_branch_id or branch_id,
        default_slot_min=DEFAULT_SLOT_MINUTES,
    )


@bp.route(_ON)
@login_required
@staff_required
def detail(number: str):
    order = _get_order(number)
    car_body_type = order.car.body_type if order.car else None
    all_services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    all_packages = ServicePackage.query.filter_by(is_active=True).order_by(ServicePackage.name).all()
    services = [s for s in all_services if matches_car_body_type(s.body_types, car_body_type)]
    packages = [p for p in all_packages if matches_car_body_type(p.body_types, car_body_type)]
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    movements = (
        InventoryMovement.query.filter_by(order_id=order.id)
        .order_by(InventoryMovement.created_at.desc())
        .all()
    )
    assigned_ids = set(get_assigned_employee_ids(order))
    bays_branch_id = branch_id_for_bays(
        request, current_user, order_branch_id=order.branch_id
    )
    bays = active_bays_for_branch(bays_branch_id) if bays_branch_id else []
    slot_start, slot_end = order_slot_bounds(order)
    slot_start_local = utc_naive_to_local(slot_start)
    slot_end_local = utc_naive_to_local(slot_end)
    activity_logs = get_entity_audit_logs("order", order.id)
    return render_template(
        "orders/detail.html",
        order=order, services=services, packages=packages,
        employees=employees, settings=Settings.get(), movements=movements,
        assigned_ids=assigned_ids,
        bays=bays,
        slot_start_local=slot_start_local,
        slot_end_local=slot_end_local,
        schedule_duration_min=order_scheduled_duration_minutes(order),
        activity_logs=activity_logs,
    )


@bp.get("/<order_number:number>/invoice/print")
@login_required
@staff_required
def invoice_print(number: str):
    order = _get_order(number)
    payment_totals = _payment_totals(order)
    settings = Settings.get()
    receipt_html = render_receipt_html(
        order,
        settings,
        cashier=current_user.name,
        payment_totals=payment_totals,
    )
    return render_template(
        "orders/invoice_print.html",
        order=order,
        settings=settings,
        receipt_html=receipt_html,
    )


@bp.post("/<order_number:number>/packages/add")
@login_required
@staff_required
def add_package(number: str):
    order = _get_order(number)
    pid = int(request.form.get("package_id"))
    pkg = db.session.get(ServicePackage, pid) or abort(400)
    car_body_type = order.car.body_type if order.car else None
    if not matches_car_body_type(pkg.body_types, car_body_type):
        flash("Пакет не подходит для типа кузова автомобиля", "error")
        return redirect(url_for("orders.detail", number=number))
    qty = float(request.form.get("qty") or 1)
    item = OrderItem(
        order_id=order.id,
        package_id=pkg.id,
        name=f"Пакет: {pkg.name}",
        price=pkg.price,
        qty=qty,
    )
    db.session.add(item)
    if order.inventory_consumed_at:
        order.inventory_consumed_at = None
        OrderMaterialPlan.query.filter_by(order_id=order.id).delete()
    log_audit(
        "order.package_add",
        entity="order",
        entity_id=order.id,
        details=f"{pkg.name} × {qty}",
    )
    db.session.commit()
    _recalc_total(order)
    flash(f"Пакет «{pkg.name}» добавлен", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/items/add")
@login_required
@staff_required
def add_item(number: str):
    order = _get_order(number)
    sid = int(request.form.get("service_id"))
    svc = db.session.get(Service, sid) or abort(400)
    car_body_type = order.car.body_type if order.car else None
    if not matches_car_body_type(svc.body_types, car_body_type):
        flash("Услуга не подходит для типа кузова автомобиля", "error")
        return redirect(url_for("orders.detail", number=number))
    qty = float(request.form.get("qty") or 1)
    item = OrderItem(order_id=order.id, service_id=svc.id, name=svc.name, price=svc.price, qty=qty)
    db.session.add(item)
    if order.inventory_consumed_at:
        order.inventory_consumed_at = None
        OrderMaterialPlan.query.filter_by(order_id=order.id).delete()
    log_audit(
        "order.item_add",
        entity="order",
        entity_id=order.id,
        details=f"{svc.name} × {qty}",
    )
    db.session.commit()
    _recalc_total(order)
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/items/<int:iid>/delete")
@login_required
@staff_required
def del_item(number: str, iid: int):
    order = _get_order(number)
    item = db.session.get(OrderItem, iid) or abort(404)
    if item.order_id != order.id:
        abort(404)
    item_name = item.name
    order_id = item.order_id
    db.session.delete(item)
    if order and order.inventory_consumed_at:
        order.inventory_consumed_at = None
        OrderMaterialPlan.query.filter_by(order_id=order.id).delete()
    log_audit(
        "order.item_remove",
        entity="order",
        entity_id=order_id,
        details=item_name,
    )
    db.session.commit()
    if order:
        _recalc_total(order)
    return redirect(url_for("orders.detail", number=number))


def _order_return_redirect(order: Order):
    from flask_login import current_user
    from ...models.user import Role
    from ...utils.worker import order_belongs_to_worker

    if current_user.role == Role.WORKER and order_belongs_to_worker(order):
        return redirect(url_for("worker.order_detail", number=order.number))
    return redirect(url_for("orders.detail", number=order.number))


@bp.route("/<order_number:number>/consume", methods=["GET", "POST"])
@login_required
@staff_required
def consume_inventory(number: str):
    order = _get_order(number)
    if order.status not in (OrderStatus.DONE, OrderStatus.DELIVERED):
        flash("Списание доступно для завершённых заказов", "warning")
        return _order_return_redirect(order)

    if request.method == "POST":
        action = request.form.get("action") or "consume"

        if action == "add":
            try:
                inv_id = int(request.form.get("inventory_item_id") or 0)
                qty = float(request.form.get("qty") or 0)
            except (TypeError, ValueError):
                inv_id, qty = 0, 0
            ok, msg = add_plan_line(order, inv_id, qty)
            flash(msg, "success" if ok else "error")
            return redirect(url_for("orders.consume_inventory", number=number))

        if action == "remove":
            try:
                plan_id = int(request.form.get("plan_id") or 0)
            except (TypeError, ValueError):
                plan_id = 0
            ok, msg = remove_plan_line(order, plan_id)
            flash(msg, "success" if ok else "error")
            return redirect(url_for("orders.consume_inventory", number=number))

        if action == "save_draft":
            rows = []
            for pid, qty in zip(request.form.getlist("plan_id"), request.form.getlist("qty")):
                try:
                    rows.append((int(pid), float(qty or 0)))
                except (TypeError, ValueError):
                    continue
            ok, msg = save_plan_draft(order, rows)
            flash(msg, "success" if ok else "error")
            return redirect(url_for("orders.consume_inventory", number=number))

        if action == "skip":
            if order_has_material_lines(order):
                flash("По заказу есть материалы — укажите количества для списания", "error")
                return redirect(url_for("orders.consume_inventory", number=number))
            order.inventory_consumed_at = datetime.utcnow()
            log_audit(
                "order.inventory_skip",
                entity="order",
                entity_id=order.id,
                details="Списание не требуется",
            )
            db.session.commit()
            flash("Списание не требуется", "success")
            return _order_return_redirect(order)

        rows = []
        for pid, qty in zip(request.form.getlist("plan_id"), request.form.getlist("qty")):
            try:
                rows.append((int(pid), float(qty or 0)))
            except (TypeError, ValueError):
                continue
        save_plan_draft(order, rows)

        quantities: dict[int, float] = {}
        for plan in order.material_plans:
            q = float(plan.qty_used or 0)
            if q > 0:
                quantities[plan.inventory_item_id] = q

        if not quantities:
            if order_has_material_lines(order):
                flash("Укажите количество для списания", "error")
                return redirect(url_for("orders.consume_inventory", number=number))
            order.inventory_consumed_at = datetime.utcnow()
            log_audit(
                "order.inventory_skip",
                entity="order",
                entity_id=order.id,
                details="Списание не требуется",
            )
            db.session.commit()
            flash("Списание не требуется", "success")
            return _order_return_redirect(order)

        was_consumed = bool(order.inventory_consumed_at)
        if was_consumed:
            ok, msg = apply_consumption_adjustment(order, quantities)
            audit_action = "inventory.consume_adjust"
        else:
            ok, msg = apply_material_consumption(order, quantities)
            audit_action = "inventory.consume"

        flash(msg, "success" if ok else "error")
        if ok:
            log_audit(
                audit_action,
                entity="order",
                entity_id=order.id,
                details=f"Заказ #{order.number}: позиций {len(quantities)}",
            )
            if was_consumed:
                return redirect(url_for("orders.consume_inventory", number=number))
            return _order_return_redirect(order)
        return redirect(url_for("orders.consume_inventory", number=number))

    plans = sync_material_plan(order)
    if order.inventory_consumed_at and not plans:
        ensure_plans_from_movements(order)
        plans = sync_material_plan(order)
    used_ids = {p.inventory_item_id for p in plans}
    inventory_items = InventoryItem.query.order_by(InventoryItem.name).all()
    applied_qty = get_applied_quantities_from_movements(order) if order.inventory_consumed_at else {}
    return render_template(
        "orders/consume.html",
        order=order,
        plans=plans,
        inventory_items=inventory_items,
        used_item_ids=used_ids,
        is_consumed=bool(order.inventory_consumed_at),
        applied_qty=applied_qty,
    )


@bp.post("/<order_number:number>/consume/refresh")
@login_required
@staff_required
def consume_refresh(number: str):
    order = _get_order(number)
    if order.inventory_consumed_at:
        sync_material_plan(order, force=True, planned_only=True)
        flash("Колонка «По шаблону» обновлена. Фактическое списание не изменено.", "info")
    else:
        sync_material_plan(order, force=True)
        flash("Шаблон материалов пересчитан по услугам", "success")
    return redirect(url_for("orders.consume_inventory", number=number))


@bp.post("/<order_number:number>/status")
@login_required
@staff_required
def set_status(number: str):
    order = _get_order(number)
    new_status = request.form.get("status")
    if new_status not in [s.value for s in OrderStatus]:
        abort(400)
    if new_status == OrderStatus.DELIVERED and not order.is_paid:
        flash(
            f"Статус «Выдан» возможен только после полной оплаты. "
            f"Остаток к оплате: {order.amount_due:.2f}",
            "error",
        )
        return redirect(url_for("orders.detail", number=number))
    old_status = order.status
    order.status = new_status
    if new_status == OrderStatus.IN_PROGRESS and not order.started_at:
        order.started_at = datetime.utcnow()
        if order.bay_id and not order.scheduled_at:
            order.scheduled_at = order.started_at
            order.scheduled_end_at = order.started_at + timedelta(
                minutes=order_duration_minutes(order)
            )
    if new_status in (OrderStatus.DONE, OrderStatus.DELIVERED) and not order.completed_at:
        order.completed_at = datetime.utcnow()
    if old_status != new_status:
        log_audit(
            "order.status",
            entity="order",
            entity_id=order.id,
            details=format_status_change(old_status, new_status),
        )
    db.session.commit()

    if new_status in (OrderStatus.DONE, OrderStatus.DELIVERED) and not order.inventory_consumed_at:
        sync_material_plan(order)
        flash("Укажите использованные материалы для списания со склада", "info")
        return redirect(url_for("orders.consume_inventory", number=number))

    s = Settings.get()
    if new_status == OrderStatus.DONE and s.evolution_send_on_ready:
        try:
            _notify_client_whatsapp(order, s.wa_template_ready, default=DEFAULT_WA_READY)
        except Exception:
            _log_notify_failure("order.set_status ready")
    try:
        notify_order_status_change(order, old_status)
    except Exception:
        _log_notify_failure("order.set_status change")

    flash("Статус обновлён", "success")
    return redirect(url_for("orders.detail", number=number))


def _parse_schedule_duration(order: Order) -> int:
    raw = (request.form.get("schedule_duration") or "").strip()
    if raw:
        try:
            return max(15, int(raw))
        except ValueError:
            pass
    return order_scheduled_duration_minutes(order)


@bp.post("/<order_number:number>/schedule")
@login_required
@staff_required
def set_schedule(number: str):
    order = _get_order(number)
    old_status = order.status
    schedule_date = (request.form.get("schedule_date") or "").strip()
    schedule_time = (request.form.get("schedule_time") or "").strip()
    scheduled_at = parse_schedule_datetime(schedule_date, schedule_time)
    if schedule_date and schedule_time and not scheduled_at:
        flash("Укажите время в формате 24ч, например 14:30", "error")
        return redirect(url_for("orders.detail", number=number))
    duration = _parse_schedule_duration(order)
    bay_id_raw = request.form.get("bay_id")
    bay_id = int(bay_id_raw) if bay_id_raw else None

    if scheduled_at:
        if not bay_id:
            flash("Выберите бокс", "error")
            return redirect(url_for("orders.detail", number=number))
        set_booked = bool(request.form.get("set_booked"))
        err = apply_order_schedule(
            order,
            bay_id=bay_id,
            scheduled_at=scheduled_at,
            duration_min=duration,
            set_booked=set_booked,
        )
        if err:
            flash(err, "error")
            return redirect(url_for("orders.detail", number=number))
    elif bay_id:
        err = apply_order_schedule(order, bay_id=bay_id, scheduled_at=None)
        if err:
            flash(err, "error")
            return redirect(url_for("orders.detail", number=number))

    slot_start, slot_end = order_slot_bounds(order)
    slot_start_local = utc_naive_to_local(slot_start)
    slot_end_local = utc_naive_to_local(slot_end)
    detail_parts = []
    if order.bay:
        detail_parts.append(order.bay.name)
    if slot_start_local and slot_end_local:
        detail_parts.append(
            f"{slot_start_local.strftime('%d.%m.%Y %H:%M')}–{slot_end_local.strftime('%H:%M')}"
        )
    log_audit(
        "order.schedule",
        entity="order",
        entity_id=order.id,
        details=" · ".join(detail_parts) if detail_parts else "Обновлено",
    )
    if old_status != order.status:
        log_audit(
            "order.status",
            entity="order",
            entity_id=order.id,
            details=format_status_change(old_status, order.status),
        )
    db.session.commit()
    try:
        notify_order_status_change(order, old_status)
    except Exception:
        _log_notify_failure("order.set_schedule")
    flash("Расписание обновлено", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/bay/occupy")
@login_required
@staff_required
def occupy_bay(number: str):
    order = _get_order(number)
    old_status = order.status
    bay_id = request.form.get("bay_id")
    if not bay_id:
        flash("Выберите бокс", "error")
        return redirect(url_for("orders.detail", number=number))
    err = occupy_bay_now(order, int(bay_id))
    if err:
        flash(err, "error")
        return redirect(url_for("orders.detail", number=number))
    bay = db.session.get(Bay, int(bay_id))
    log_audit(
        "order.bay_occupy",
        entity="order",
        entity_id=order.id,
        details=f"Бокс «{bay.name}»" if bay else f"Бокс #{bay_id}",
    )
    if old_status != order.status:
        log_audit(
            "order.status",
            entity="order",
            entity_id=order.id,
            details=format_status_change(old_status, order.status),
        )
    db.session.commit()
    try:
        notify_order_status_change(order, old_status)
    except Exception:
        _log_notify_failure("order.occupy_bay")
    flash("Бокс занят, заказ в работе", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/discount")
@login_required
@manager_required
def set_discount(number: str):
    order = _get_order(number)
    order.discount_type = request.form.get("discount_type") or None
    order.discount_value = float(request.form.get("discount_value") or 0)
    order.discount_reason = request.form.get("discount_reason", "")
    log_audit(
        "order.discount",
        entity="order",
        entity_id=order.id,
        details=f"{order.discount_type or '—'} {order.discount_value} — {order.discount_reason}",
    )
    db.session.commit()
    _recalc_total(order)
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/bonus")
@login_required
@staff_required
def apply_bonus(number: str):
    order = _get_order(number)
    raw = float(request.form.get("amount") or 0)
    if raw < 0:
        flash("Сумма списания не может быть отрицательной", "error")
        return redirect(url_for("orders.detail", number=number))
    s = Settings.get()
    if not s.bonus_enabled:
        flash("Бонусы отключены", "error")
        return redirect(url_for("orders.detail", number=number))
    max_allowed = (order.subtotal or 0) * (s.bonus_max_percent_of_order / 100)
    wallet = order.client.wallet
    if not wallet:
        wallet = BonusWallet(client_id=order.client_id)
        db.session.add(wallet)
        db.session.commit()
    amount = max(0.0, min(raw, max_allowed, wallet.balance or 0))
    order.bonus_used = amount
    log_audit(
        "order.bonus",
        entity="order",
        entity_id=order.id,
        details=f"Списано {amount:.2f}",
    )
    db.session.commit()
    _recalc_total(order)
    flash(f"Применено бонусов: {amount:.2f}", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/payments")
@login_required
@staff_required
def add_payment(number: str):
    order = _get_order(number)
    method = request.form.get("method") or PaymentMethod.CASH
    amount = float(request.form.get("amount") or 0)
    if amount < 0:
        flash("Сумма оплаты не может быть отрицательной", "error")
        return redirect(url_for("orders.detail", number=number))

    p = Payment(order_id=order.id, method=method, amount=amount, status=PaymentStatus.SUCCESS)

    if method == PaymentMethod.AZERICARD:
        from ...services.azericard import AzericardService

        az = AzericardService()
        if not az.enabled:
            flash(
                "Azericard не настроен: укажите Terminal, Merchant Name/URL и RSA private key.",
                "error",
            )
            return redirect(url_for("orders.detail", number=number))
        p.status = PaymentStatus.PENDING
        db.session.add(p)
        db.session.flush()
        az.create_payment_link(
            payment=p,
            business_order_id=order.id,
            amount=amount,
        )
        log_audit(
            "order.payment",
            entity="order",
            entity_id=order.id,
            details=f"{p.method_label}: {amount:.2f} (ожидает оплаты)",
        )
        db.session.commit()
        flash("Ссылка на оплату создана. Отправьте её клиенту в WhatsApp.", "success")
        return redirect(url_for("orders.detail", number=number))

    if method == PaymentMethod.BONUS:
        if amount <= 0:
            flash("Укажите положительную сумму списания бонусов", "error")
            return redirect(url_for("orders.detail", number=number))
        wallet = order.client.wallet
        if not wallet or wallet.balance < amount:
            flash("Недостаточно бонусов", "error")
            return redirect(url_for("orders.detail", number=number))
        wallet.balance = max(wallet.balance - amount, 0.0)
        wallet.lifetime_spent += amount
        db.session.add(BonusTransaction(
            client_id=order.client_id, type=BonusType.SPEND,
            amount=amount, source_order_id=order.id,
        ))

    db.session.add(p)
    log_audit(
        "order.payment",
        entity="order",
        entity_id=order.id,
        details=f"{p.method_label}: {amount:.2f}",
    )
    db.session.commit()

    from ...services.order_payments import apply_cashback_if_order_paid

    apply_cashback_if_order_paid(order.id)

    flash("Оплата зафиксирована", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/payments/<int:pid>/send-pay-link")
@login_required
@staff_required
def send_azericard_pay_link(number: str, pid: int):
    """Отправить клиенту ссылку на оплату Azericard в WhatsApp."""
    order = _get_order(number)
    payment = Payment.query.filter_by(id=pid, order_id=order.id).first_or_404()

    if payment.method != PaymentMethod.AZERICARD:
        flash("Это не платёж Azericard", "error")
        return redirect(url_for("orders.detail", number=number))
    if payment.status != PaymentStatus.PENDING:
        flash("Платёж уже обработан", "warning")
        return redirect(url_for("orders.detail", number=number))

    intent = payment.azericard_intent
    if not intent or not intent.pay_token:
        flash("Ссылка на оплату не найдена", "error")
        return redirect(url_for("orders.detail", number=number))

    if not order.client.phone:
        flash("У клиента не указан телефон", "error")
        return redirect(url_for("orders.detail", number=number))

    s = Settings.get()
    if not s.evolution_enabled:
        flash("WhatsApp (Evolution API) отключён в настройках", "error")
        return redirect(url_for("orders.detail", number=number))

    pay_link = url_for("payments.pay_checkout", token=intent.pay_token, _external=True)
    svc = EvolutionAPIService(s)
    if not svc.enabled:
        flash("WhatsApp не настроен полностью", "error")
        return redirect(url_for("orders.detail", number=number))

    msg = format_whatsapp_message(
        s.wa_template_payment,
        s,
        default=DEFAULT_WA_PAYMENT,
        order_number=order.number,
        client_name=order.client.name,
        amount=f"{payment.amount:.2f} AZN",
        payment_link=pay_link,
    )
    ok, detail = svc.send_text(order.client.phone, msg)
    if ok:
        flash("Ссылка на оплату отправлена в WhatsApp", "success")
        log_audit(
            "order.payment_link_sent",
            entity="order",
            entity_id=order.id,
            details=f"payment#{payment.id} {pay_link[:80]}",
        )
        db.session.commit()
    else:
        flash(f"Не удалось отправить WhatsApp: {detail[:200]}", "error")
    return redirect(url_for("orders.detail", number=number))


@bp.post("/<order_number:number>/photos")
@login_required
@staff_required
def add_photo(number: str):
    order = _get_order(number)
    files = request.files.getlist("photos")
    kind = request.form.get("kind", "before")
    uploaded = 0
    for f in files:
        rel = save_upload(f, subdir=f"orders/{order.id}", allowed=ALLOWED_IMAGE)
        if rel:
            db.session.add(OrderPhoto(order_id=order.id, filename=rel, kind=kind))
            uploaded += 1
    if uploaded:
        kind_label = "До" if kind == "before" else "После"
        log_audit(
            "order.photo",
            entity="order",
            entity_id=order.id,
            details=f"{kind_label}: {uploaded} шт.",
        )
    db.session.commit()
    flash("Фото загружены", "success")
    return redirect(url_for("orders.detail", number=number))


@bp.get("/<order_number:number>/photos/<int:pid>/file")
@login_required
@staff_required
def photo_file(number: str, pid: int):
    """Serve an order photo only to users with access to the order's branch."""
    order = _get_order(number)
    photo = db.session.get(OrderPhoto, pid) or abort(404)
    if photo.order_id != order.id:
        abort(404)
    base = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    full = (base / photo.filename).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        abort(404)
    if not full.is_file():
        abort(404)
    return send_file(full)


@bp.post("/<order_number:number>/assign")
@login_required
@manager_required
def assign(number: str):
    order = _get_order(number)
    raw_ids = request.form.getlist("employee_ids")
    employee_ids = [int(x) for x in raw_ids if x and str(x).isdigit()]
    sync_order_assignees(order, employee_ids)
    names = order.assignee_names
    log_audit(
        "order.assign",
        entity="order",
        entity_id=order.id,
        details=f"#{order.number}: {names}",
    )
    db.session.commit()
    from ...utils.i18n import translate
    flash(translate("orders.executors_saved"), "success")
    return redirect(url_for("orders.detail", number=number))


# ---- Cars by client (AJAX) ---- #
@bp.get("/api/cars/<int:cid>")
@login_required
@staff_required
def cars_for_client(cid: int):
    cars = Car.query.filter_by(client_id=cid).all()
    return jsonify([
        {"id": c.id, "display": c.display, "body_type": c.body_type}
        for c in cars
    ])


@bp.get("/api/bays/<int:branch_id>")
@login_required
@staff_required
def bays_for_branch(branch_id: int):
    from ...models.branch import Branch

    if not Branch.query.filter_by(id=branch_id, is_active=True).first():
        abort(404)
    bays = active_bays_for_branch(branch_id)
    return jsonify([
        {"id": b.id, "name": b.name, "capabilities": b.capability_labels}
        for b in bays
    ])


# ---- helpers ---- #

def _recalc_total(order: Order) -> None:
    subtotal = sum((i.qty or 0) * (i.price or 0) for i in order.items)
    discount = 0.0
    if order.discount_type == "fixed":
        discount = order.discount_value or 0
    elif order.discount_type in ("percent", "manual"):
        discount = subtotal * (order.discount_value or 0) / 100
    bonus_used = max(order.bonus_used or 0, 0)
    after_discount = max(subtotal - discount - bonus_used, 0)
    s = Settings.get()
    if s.vat_included_in_price:
        vat = after_discount - after_discount / (1 + s.vat_rate / 100)
    else:
        vat = after_discount * s.vat_rate / 100
        after_discount += vat

    order.subtotal = round(subtotal, 2)
    order.vat_amount = round(vat, 2)
    order.final_total = round(after_discount, 2)
    db.session.commit()
