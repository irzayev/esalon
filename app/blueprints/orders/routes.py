"""Orders: list / create / view / status / payments / photos."""
import re
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, send_file
from flask_login import login_required, current_user

from ...extensions import db
from ...models.order import Order, OrderItem, OrderStatus, OrderPhoto
from ...models.client import Client, Car
from ...models.service import Service, ServicePackage
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
from ...utils.audit import log_audit
from ...utils.branches import (
    effective_branch_id,
    filter_orders,
    get_active_branches,
    multi_branch_enabled,
    resolve_order_branch_id,
)
from ...utils.decorators import staff_required, manager_required
from ...utils.uploads import save_upload, ALLOWED_IMAGE
from ...services.evolution_api import EvolutionAPIService
from ...services.branding import (
    format_whatsapp_message,
    DEFAULT_WA_READY,
    DEFAULT_WA_BOOKING,
)
from ...services.invoice_pdf import build_order_invoice_pdf
from ...services.receipt import render_receipt_html, _payment_totals
from ...services.order_assignees import (
    sync_order_assignees,
    get_assigned_employee_ids,
    orders_with_assignees_query,
)

bp = Blueprint("orders", __name__)


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
        client_id = int(request.form.get("client_id"))
        client = db.session.get(Client, client_id) or abort(400)
        car_id = request.form.get("car_id")
        order = Order(
            client_id=client.id,
            car_id=int(car_id) if car_id else None,
            branch_id=resolve_order_branch_id(
                request, current_user, form_value=request.form.get("branch_id")
            ),
            created_by_id=current_user.id,
            status=OrderStatus.NEW,
            notes=request.form.get("notes", ""),
        )
        order.number = _next_order_number()
        db.session.add(order)
        db.session.flush()
        car_label = order.car.display if order.car else "без авто"
        log_audit(
            "order.create",
            entity="order",
            entity_id=order.id,
            details=f"#{order.number} · {client.name} ({client.phone}) · {car_label}",
        )
        db.session.commit()
        _recalc_total(order)

        s = Settings.get()
        if s.evolution_send_on_booking:
            try:
                _notify_client_whatsapp(order, s.wa_template_booking, default=DEFAULT_WA_BOOKING)
            except Exception:
                pass

        return redirect(url_for("orders.detail", oid=order.id))

    clients = Client.query.order_by(Client.name).all()
    branches = get_active_branches()
    return render_template(
        "orders/new.html",
        clients=clients,
        branches=branches,
        show_branch_select=len(branches) > 1 and not current_user.branch_id,
        default_branch_id=effective_branch_id(request, current_user),
    )


@bp.route("/<int:oid>")
@login_required
@staff_required
def detail(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    packages = ServicePackage.query.filter_by(is_active=True).order_by(ServicePackage.name).all()
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    movements = (
        InventoryMovement.query.filter_by(order_id=order.id)
        .order_by(InventoryMovement.created_at.desc())
        .all()
    )
    assigned_ids = set(get_assigned_employee_ids(order))
    return render_template(
        "orders/detail.html",
        order=order, services=services, packages=packages,
        employees=employees, settings=Settings.get(), movements=movements,
        assigned_ids=assigned_ids,
    )


@bp.get("/<int:oid>/invoice.pdf")
@login_required
@staff_required
def invoice_pdf(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    pdf_data = build_order_invoice_pdf(
        order,
        cashier=current_user.name,
        base_url=request.url_root.rstrip("/"),
    )
    db.session.add(
        AuditLog(
            user_id=current_user.id,
            action="order.invoice_pdf",
            entity="order",
            entity_id=order.id,
            details=f"Invoice #{order.number}",
            ip=request.remote_addr,
        )
    )
    db.session.commit()
    return send_file(
        BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"invoice-{order.number}.pdf",
    )


@bp.get("/<int:oid>/invoice/print")
@login_required
@staff_required
def invoice_print(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    payment_totals = _payment_totals(order)
    db.session.add(
        AuditLog(
            user_id=current_user.id,
            action="order.invoice_print_view",
            entity="order",
            entity_id=order.id,
            details=f"Print view #{order.number}",
            ip=request.remote_addr,
        )
    )
    db.session.commit()
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


@bp.post("/<int:oid>/packages/add")
@login_required
@staff_required
def add_package(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    pid = int(request.form.get("package_id"))
    pkg = db.session.get(ServicePackage, pid) or abort(400)
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
    db.session.commit()
    _recalc_total(order)
    flash(f"Пакет «{pkg.name}» добавлен", "success")
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/items/add")
@login_required
@staff_required
def add_item(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    sid = int(request.form.get("service_id"))
    svc = db.session.get(Service, sid) or abort(400)
    qty = float(request.form.get("qty") or 1)
    item = OrderItem(order_id=order.id, service_id=svc.id, name=svc.name, price=svc.price, qty=qty)
    db.session.add(item)
    if order.inventory_consumed_at:
        order.inventory_consumed_at = None
        OrderMaterialPlan.query.filter_by(order_id=order.id).delete()
    db.session.commit()
    _recalc_total(order)
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/items/<int:iid>/delete")
@login_required
@staff_required
def del_item(oid: int, iid: int):
    item = db.session.get(OrderItem, iid) or abort(404)
    db.session.delete(item)
    order = db.session.get(Order, oid)
    if order and order.inventory_consumed_at:
        order.inventory_consumed_at = None
        OrderMaterialPlan.query.filter_by(order_id=order.id).delete()
    db.session.commit()
    if order:
        _recalc_total(order)
    return redirect(url_for("orders.detail", oid=oid))


def _order_return_redirect(order: Order):
    from flask_login import current_user
    from ...models.user import Role
    from ...utils.worker import order_belongs_to_worker

    if current_user.role == Role.WORKER and order_belongs_to_worker(order):
        return redirect(url_for("worker.order_detail", oid=order.id))
    return redirect(url_for("orders.detail", oid=order.id))


@bp.route("/<int:oid>/consume", methods=["GET", "POST"])
@login_required
@staff_required
def consume_inventory(oid: int):
    order = db.session.get(Order, oid) or abort(404)
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
            return redirect(url_for("orders.consume_inventory", oid=oid))

        if action == "remove":
            try:
                plan_id = int(request.form.get("plan_id") or 0)
            except (TypeError, ValueError):
                plan_id = 0
            ok, msg = remove_plan_line(order, plan_id)
            flash(msg, "success" if ok else "error")
            return redirect(url_for("orders.consume_inventory", oid=oid))

        if action == "save_draft":
            rows = []
            for pid, qty in zip(request.form.getlist("plan_id"), request.form.getlist("qty")):
                try:
                    rows.append((int(pid), float(qty or 0)))
                except (TypeError, ValueError):
                    continue
            ok, msg = save_plan_draft(order, rows)
            flash(msg, "success" if ok else "error")
            return redirect(url_for("orders.consume_inventory", oid=oid))

        if action == "skip":
            if order_has_material_lines(order):
                flash("По заказу есть материалы — укажите количества для списания", "error")
                return redirect(url_for("orders.consume_inventory", oid=oid))
            order.inventory_consumed_at = datetime.utcnow()
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
                return redirect(url_for("orders.consume_inventory", oid=oid))
            order.inventory_consumed_at = datetime.utcnow()
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
                return redirect(url_for("orders.consume_inventory", oid=oid))
            return _order_return_redirect(order)
        return redirect(url_for("orders.consume_inventory", oid=oid))

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


@bp.post("/<int:oid>/consume/refresh")
@login_required
@staff_required
def consume_refresh(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    if order.inventory_consumed_at:
        sync_material_plan(order, force=True, planned_only=True)
        flash("Колонка «По шаблону» обновлена. Фактическое списание не изменено.", "info")
    else:
        sync_material_plan(order, force=True)
        flash("Шаблон материалов пересчитан по услугам", "success")
    return redirect(url_for("orders.consume_inventory", oid=oid))


@bp.post("/<int:oid>/status")
@login_required
@staff_required
def set_status(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    new_status = request.form.get("status")
    if new_status not in [s.value for s in OrderStatus]:
        abort(400)
    order.status = new_status
    if new_status == OrderStatus.IN_PROGRESS and not order.started_at:
        order.started_at = datetime.utcnow()
    if new_status in (OrderStatus.DONE, OrderStatus.DELIVERED) and not order.completed_at:
        order.completed_at = datetime.utcnow()
    db.session.commit()

    if new_status in (OrderStatus.DONE, OrderStatus.DELIVERED) and not order.inventory_consumed_at:
        sync_material_plan(order)
        flash("Укажите использованные материалы для списания со склада", "info")
        return redirect(url_for("orders.consume_inventory", oid=oid))

    s = Settings.get()
    if new_status == OrderStatus.DONE and s.evolution_send_on_ready:
        try:
            _notify_client_whatsapp(order, s.wa_template_ready, default=DEFAULT_WA_READY)
        except Exception:
            pass

    flash("Статус обновлён", "success")
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/discount")
@login_required
@manager_required
def set_discount(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    order.discount_type = request.form.get("discount_type") or None
    order.discount_value = float(request.form.get("discount_value") or 0)
    order.discount_reason = request.form.get("discount_reason", "")
    db.session.add(AuditLog(
        user_id=current_user.id, action="order.discount", entity="order",
        entity_id=order.id,
        details=f"{order.discount_type} {order.discount_value} — {order.discount_reason}",
        ip=request.remote_addr,
    ))
    db.session.commit()
    _recalc_total(order)
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/bonus")
@login_required
@staff_required
def apply_bonus(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    amount = float(request.form.get("amount") or 0)
    s = Settings.get()
    if not s.bonus_enabled:
        flash("Бонусы отключены", "error")
        return redirect(url_for("orders.detail", oid=oid))
    max_allowed = (order.subtotal or 0) * (s.bonus_max_percent_of_order / 100)
    wallet = order.client.wallet
    if not wallet:
        wallet = BonusWallet(client_id=order.client_id)
        db.session.add(wallet)
        db.session.commit()
    amount = min(amount, max_allowed, wallet.balance)
    order.bonus_used = amount
    db.session.commit()
    _recalc_total(order)
    flash(f"Применено бонусов: {amount:.2f}", "success")
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/payments")
@login_required
@staff_required
def add_payment(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    method = request.form.get("method") or PaymentMethod.CASH
    amount = float(request.form.get("amount") or 0)

    p = Payment(order_id=order.id, method=method, amount=amount, status=PaymentStatus.SUCCESS)

    if method == PaymentMethod.AZERICARD:
        from ...services.azericard import AzericardService, AzericardPayment
        az = AzericardService()
        if not az.enabled:
            flash("Azericard не настроен", "error")
            return redirect(url_for("orders.detail", oid=oid))
        p.status = PaymentStatus.PENDING
        db.session.add(p)
        db.session.commit()
        payload = az.build_form_payload(AzericardPayment(
            order_id=order.id, amount=amount,
            description=f"Order #{order.number}",
            back_ref_url=url_for("orders.detail", oid=order.id, _external=True),
        ))
        return render_template("orders/azericard_redirect.html",
                               gateway=az.gateway_url, payload=payload)

    if method == PaymentMethod.BONUS:
        wallet = order.client.wallet
        if not wallet or wallet.balance < amount:
            flash("Недостаточно бонусов", "error")
            return redirect(url_for("orders.detail", oid=oid))
        wallet.balance -= amount
        wallet.lifetime_spent += amount
        db.session.add(BonusTransaction(
            client_id=order.client_id, type=BonusType.SPEND,
            amount=amount, source_order_id=order.id,
        ))

    db.session.add(p)
    db.session.commit()

    # Cashback
    s = Settings.get()
    if s.bonus_enabled and order.is_paid and method != PaymentMethod.BONUS:
        cashback = round((order.final_total or 0) * s.bonus_cashback_percent / 100, 2)
        if cashback > 0:
            wallet = order.client.wallet
            if not wallet:
                wallet = BonusWallet(client_id=order.client_id)
                db.session.add(wallet)
            wallet.balance += cashback
            wallet.lifetime_earned += cashback
            db.session.add(BonusTransaction(
                client_id=order.client_id, type=BonusType.EARN,
                amount=cashback, source_order_id=order.id,
                comment="cashback",
            ))
            db.session.commit()

    flash("Оплата зафиксирована", "success")
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/photos")
@login_required
@staff_required
def add_photo(oid: int):
    order = db.session.get(Order, oid) or abort(404)
    files = request.files.getlist("photos")
    kind = request.form.get("kind", "before")
    for f in files:
        rel = save_upload(f, subdir=f"orders/{order.id}", allowed=ALLOWED_IMAGE)
        if rel:
            db.session.add(OrderPhoto(order_id=order.id, filename=rel, kind=kind))
    db.session.commit()
    flash("Фото загружены", "success")
    return redirect(url_for("orders.detail", oid=oid))


@bp.post("/<int:oid>/assign")
@login_required
@manager_required
def assign(oid: int):
    order = db.session.get(Order, oid) or abort(404)
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
    return redirect(url_for("orders.detail", oid=oid))


# ---- Cars by client (AJAX) ---- #
@bp.get("/api/cars/<int:cid>")
@login_required
@staff_required
def cars_for_client(cid: int):
    cars = Car.query.filter_by(client_id=cid).all()
    return jsonify([{"id": c.id, "display": c.display} for c in cars])


# ---- helpers ---- #

def _next_order_number() -> str:
    """Format: DDMM-XXX (e.g. 2805-001 for 28 May, first order of the day)."""
    s = Settings.get()
    tz_name = (s.timezone or "Asia/Baku").strip() or "Asia/Baku"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Baku")
    prefix = datetime.now(tz).strftime("%d%m")
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}})$")
    max_seq = 0
    for (number,) in db.session.query(Order.number).filter(Order.number.like(f"{prefix}-%")):
        if number and (m := pattern.match(number)):
            max_seq = max(max_seq, int(m.group(1)))
    return f"{prefix}-{max_seq + 1:03d}"


def _recalc_total(order: Order) -> None:
    subtotal = sum((i.qty or 0) * (i.price or 0) for i in order.items)
    discount = 0.0
    if order.discount_type == "fixed":
        discount = order.discount_value or 0
    elif order.discount_type in ("percent", "manual"):
        discount = subtotal * (order.discount_value or 0) / 100
    after_discount = max(subtotal - discount - (order.bonus_used or 0), 0)
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
