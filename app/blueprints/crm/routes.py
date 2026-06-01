from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ...extensions import db
from ...models.client import Client, Car, ClientLevel, CarBodyType
from ...models.order import Order, VISIT_STATUSES
from ...utils.i18n import get_body_type_choices
from ...models.bonus import BonusWallet, BonusTransaction
from ...utils.audit import log_audit
from ...utils.decorators import staff_required
from ...models.settings import Settings
from ...services.whatsapp_messages import broadcast_message, send_text_to_client
from ...services.branding import format_whatsapp_message
from ...utils.whatsapp_templates import (
    all_template_entries,
    broadcast_template_entries,
    is_broadcast_template_key,
    template_body_by_key,
)
from ...utils.client_fields import (
    normalize_phone,
    validate_phone,
    normalize_plate,
    validate_plate,
    parse_birthday,
)
from ...utils.pagination import (
    LIST_PER_PAGE_CHOICES,
    list_page,
    list_per_page,
    pagination_page_numbers,
)

bp = Blueprint("crm", __name__)


def _body_types():
    return get_body_type_choices()


_CLIENT_SORT_KEYS = frozenset(
    {
        "name",
        "phone",
        "level",
        "cars_count",
        "orders_count",
        "avg_check",
        "last_visit",
        "created_at",
    }
)

_NULLABLE_SORT_KEYS = frozenset({"last_visit", "avg_check", "orders_count", "phone"})

def _client_list_subqueries():
    visit_at = func.coalesce(
        Order.completed_at, Order.started_at, Order.created_at
    )
    last_visit = (
        select(
            Order.client_id,
            func.max(visit_at).label("last_visit_at"),
        )
        .where(Order.status.in_(VISIT_STATUSES))
        .group_by(Order.client_id)
        .subquery()
    )
    orders_count = (
        select(Order.client_id, func.count(Order.id).label("orders_count"))
        .group_by(Order.client_id)
        .subquery()
    )
    avg_check = (
        select(Order.client_id, func.avg(Order.final_total).label("avg_check"))
        .group_by(Order.client_id)
        .subquery()
    )
    cars_count = (
        select(Car.client_id, func.count(Car.id).label("cars_count"))
        .group_by(Car.client_id)
        .subquery()
    )
    return last_visit, orders_count, avg_check, cars_count


@bp.route("/")
@login_required
@staff_required
def clients():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "last_visit")
    direction = request.args.get("dir", "desc")
    if sort not in _CLIENT_SORT_KEYS:
        sort = "last_visit"
    if direction not in ("asc", "desc"):
        direction = "desc"

    last_visit_sq, orders_count_sq, avg_check_sq, cars_count_sq = _client_list_subqueries()

    query = (
        Client.query.outerjoin(last_visit_sq, Client.id == last_visit_sq.c.client_id)
        .outerjoin(orders_count_sq, Client.id == orders_count_sq.c.client_id)
        .outerjoin(avg_check_sq, Client.id == avg_check_sq.c.client_id)
        .outerjoin(cars_count_sq, Client.id == cars_count_sq.c.client_id)
        .add_columns(
            last_visit_sq.c.last_visit_at,
            func.coalesce(orders_count_sq.c.orders_count, 0).label("orders_count_val"),
            func.coalesce(avg_check_sq.c.avg_check, 0.0).label("avg_check_val"),
            func.coalesce(cars_count_sq.c.cars_count, 0).label("cars_count_val"),
        )
    )
    if q:
        phone_q = normalize_phone(q)
        like = f"%{q}%"
        filters = [Client.name.ilike(like)]
        if phone_q:
            filters.append(Client.phone.ilike(f"%{phone_q}%"))
        else:
            filters.append(Client.phone.ilike(like))
        query = query.filter(or_(*filters))

    sort_map = {
        "name": Client.name,
        "phone": Client.phone,
        "level": Client.level,
        "cars_count": func.coalesce(cars_count_sq.c.cars_count, 0),
        "orders_count": func.coalesce(orders_count_sq.c.orders_count, 0),
        "avg_check": func.coalesce(avg_check_sq.c.avg_check, 0.0),
        "last_visit": last_visit_sq.c.last_visit_at,
        "created_at": Client.created_at,
    }
    sort_col = sort_map[sort]
    order = sort_col.asc() if direction == "asc" else sort_col.desc()
    if sort in _NULLABLE_SORT_KEYS:
        order = order.nullsfirst() if direction == "asc" else order.nullslast()
    tiebreaker = Client.name.asc()

    per_page = list_per_page(request.args.get("per_page"))
    total = query.order_by(None).count()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page = list_page(request.args.get("page"), total_pages)
    offset = (page - 1) * per_page

    items = []
    page_query = query.options(joinedload(Client.cars))
    for client, last_visit_at, orders_count_val, avg_check_val, cars_count_val in (
        page_query.order_by(order, tiebreaker).offset(offset).limit(per_page).all()
    ):
        client.visit_at = last_visit_at
        client.list_orders_count = int(orders_count_val or 0)
        client.list_avg_check = float(avg_check_val or 0)
        items.append(client)

    def sort_dir(col: str) -> str:
        if sort == col and direction == "asc":
            return "desc"
        return "asc"

    range_start = offset + 1 if total else 0
    range_end = offset + len(items) if total else 0
    list_query = {"sort": sort, "dir": direction}
    if q:
        list_query["q"] = q

    return render_template(
        "crm/clients.html",
        clients=items,
        q=q,
        sort=sort,
        sort_direction=direction,
        toggle_sort_dir=sort_dir,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        range_start=range_start,
        range_end=range_end,
        per_page_choices=LIST_PER_PAGE_CHOICES,
        page_numbers=pagination_page_numbers(page, total_pages),
        list_query=list_query,
        wa_templates=all_template_entries(),
        wa_broadcast_templates=broadcast_template_entries(),
    )


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required
@staff_required
def client_new():
    if request.method == "POST":
        c = Client()
        if not _save_client(c):
            return render_template(
                "crm/client_form.html",
                client=None,
                levels=list(ClientLevel),
                body_types=_body_types(),
                form=request.form,
            )
        _save_cars_from_form(c)
        return redirect(url_for("crm.client_detail", cid=c.id))
    return render_template(
        "crm/client_form.html",
        client=None,
        levels=list(ClientLevel),
        body_types=_body_types(),
        form=None,
    )


@bp.route("/clients/<int:cid>", methods=["GET"])
@login_required
@staff_required
def client_detail(cid: int):
    c = db.session.get(Client, cid) or abort(404)
    if not c.wallet:
        db.session.add(BonusWallet(client_id=c.id))
        db.session.commit()
    bonus_history = (
        BonusTransaction.query.filter_by(client_id=c.id)
        .order_by(BonusTransaction.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "crm/client_detail.html",
        client=c,
        bonus_history=bonus_history,
        body_types=_body_types(),
        wa_templates=all_template_entries(),
    )


@bp.route("/clients/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@staff_required
def client_edit(cid: int):
    c = db.session.get(Client, cid) or abort(404)
    if request.method == "POST":
        if not _save_client(c):
            return render_template(
                "crm/client_form.html",
                client=c,
                levels=list(ClientLevel),
                body_types=_body_types(),
                form=request.form,
            )
        _save_cars_from_form(c)
        return redirect(url_for("crm.client_detail", cid=c.id))
    return render_template(
        "crm/client_form.html",
        client=c,
        levels=list(ClientLevel),
        body_types=_body_types(),
        form=None,
    )


@bp.post("/clients/<int:cid>/delete")
@login_required
@staff_required
def client_delete(cid: int):
    c = db.session.get(Client, cid) or abort(404)
    # Orders reference the client with a NOT NULL FK; deleting a client that
    # has orders would raise an IntegrityError. Refuse with a clear message.
    order_count = Order.query.filter_by(client_id=c.id).count()
    if order_count:
        flash(
            f"Нельзя удалить клиента: есть связанные заказы ({order_count}).",
            "error",
        )
        return redirect(url_for("crm.client_detail", cid=c.id))
    try:
        db.session.delete(c)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Нельзя удалить клиента: есть связанные данные.", "error")
        return redirect(url_for("crm.client_detail", cid=c.id))
    flash("Клиент удалён", "success")
    return redirect(url_for("crm.clients"))


@bp.post("/whatsapp/send")
@login_required
@staff_required
def whatsapp_send():
    client = db.session.get(Client, int(request.form.get("client_id") or 0)) or abort(404)
    template_key = (request.form.get("template_key") or "").strip()
    custom_text = (request.form.get("custom_text") or "").strip()

    if custom_text:
        text = custom_text
    elif not template_key:
        flash("Выберите шаблон или введите свой текст", "error")
        return redirect(request.referrer or url_for("crm.clients"))
    else:
        body_tpl = template_body_by_key(template_key)
        if not body_tpl:
            flash("Выберите шаблон сообщения", "error")
            return redirect(request.referrer or url_for("crm.clients"))
        text = format_whatsapp_message(
            body_tpl,
            Settings.get(),
            default=body_tpl,
            client_name=client.name,
        )

    ok, msg = send_text_to_client(
        client,
        text,
        mark_reminder=template_key == "reminder",
    )
    if ok:
        log_audit(
            "whatsapp.send",
            entity="client",
            entity_id=client.id,
            details=f"{client.name} · {client.phone}",
        )
        db.session.commit()
        flash(f"Сообщение отправлено: {client.name}", "success")
    else:
        flash(f"Не удалось отправить: {msg[:200]}", "error")

    return redirect(request.referrer or url_for("crm.client_detail", cid=client.id))


@bp.post("/whatsapp/broadcast")
@login_required
@staff_required
def whatsapp_broadcast():
    template_key = (request.form.get("template_key") or "").strip()
    if not template_key:
        flash("Выберите шаблон для рассылки", "error")
        return redirect(url_for("crm.clients"))
    if not is_broadcast_template_key(template_key):
        flash("Этот шаблон нельзя использовать для массовой рассылки", "error")
        return redirect(url_for("crm.clients"))

    raw_ids = request.form.getlist("client_ids")
    client_ids = [int(x) for x in raw_ids if str(x).isdigit()] or None

    result = broadcast_message(
        template_key,
        client_ids,
        mark_as_reminder=template_key == "reminder",
    )
    if result.get("error"):
        flash(f"Рассылка не выполнена: {result['error']}", "error")
        return redirect(url_for("crm.clients"))

    log_audit(
        "whatsapp.broadcast",
        entity="system",
        details=f"шаблон {template_key} · отправлено {result.get('sent', 0)} · ошибок {result.get('failed', 0)}",
    )
    db.session.commit()
    flash(
        f"Рассылка завершена: отправлено {result.get('sent', 0)}, "
        f"ошибок {result.get('failed', 0)}",
        "success" if result.get("sent") else "warning",
    )
    return redirect(url_for("crm.clients"))


def _save_client(c: Client) -> bool:
    f = request.form
    c.name = f.get("name", "").strip()
    phone = normalize_phone(f.get("phone", ""))
    ok, msg = validate_phone(phone)
    if not ok:
        flash(msg, "error")
        return False
    dup = Client.query.filter(Client.phone == phone, Client.id != c.id).first()
    if dup:
        flash(f"Телефон уже используется клиентом «{dup.name}»", "error")
        return False
    c.phone = phone
    c.level = f.get("level") or ClientLevel.REGULAR
    bday_raw = f.get("birthday", "")
    bday, bday_err = parse_birthday(bday_raw)
    if bday_err:
        flash(bday_err, "error")
        return False
    c.birthday = bday
    c.notes = f.get("notes", "")
    if not c.id:
        db.session.add(c)
    db.session.commit()
    flash("Клиент сохранён", "success")
    return True


def _save_cars_from_form(client: Client) -> None:
    brands = request.form.getlist("car_brand[]")
    models = request.form.getlist("car_model[]")
    types = request.form.getlist("car_body_type[]")
    plates = request.form.getlist("car_plate[]")
    added = 0
    for brand, model, body_type, plate_raw in zip(brands, models, types, plates):
        brand = brand.strip()
        model = model.strip()
        plate_raw = (plate_raw or "").strip()
        if not (brand or model or plate_raw):
            continue
        plate = normalize_plate(plate_raw)
        car = Car(client_id=client.id)
        if not _apply_car_fields(car, brand, model, body_type, plate):
            continue
        added += 1
    if added:
        flash(f"Добавлено автомобилей: {added}", "success")


def _apply_car_fields(
    car: Car, brand: str, model: str, body_type: str, plate: str
) -> bool:
    if not brand or not model:
        flash("Для автомобиля укажите марку и модель", "error")
        return False
    if body_type not in {t.value for t in CarBodyType}:
        flash("Выберите тип кузова", "error")
        return False
    ok, msg = validate_plate(plate)
    if not ok:
        flash(msg, "error")
        return False
    car.brand = brand
    car.model = model
    car.body_type = body_type
    car.plate = plate
    is_new = not car.id
    if is_new:
        db.session.add(car)
    db.session.flush()
    client = db.session.get(Client, car.client_id)
    client_phone = client.phone if client else ""
    log_audit(
        "car.create" if is_new else "car.update",
        entity="car",
        entity_id=car.id,
        details=f"{brand} {model} {plate} · клиент {client_phone}",
    )
    db.session.commit()
    return True


# ---- Cars ---- #

@bp.route("/clients/<int:cid>/cars/new", methods=["POST"])
@login_required
@staff_required
def car_new(cid: int):
    client = db.session.get(Client, cid) or abort(404)
    car = Car(client_id=client.id)
    brand = request.form.get("brand", "").strip()
    model = request.form.get("model", "").strip()
    body_type = request.form.get("body_type", "")
    plate = normalize_plate(request.form.get("plate", ""))
    if _apply_car_fields(car, brand, model, body_type, plate):
        flash("Автомобиль добавлен", "success")
    return redirect(url_for("crm.client_detail", cid=cid))


@bp.route("/cars/<int:car_id>/edit", methods=["GET", "POST"])
@login_required
@staff_required
def car_edit(car_id: int):
    car = db.session.get(Car, car_id) or abort(404)
    if request.method == "POST":
        brand = request.form.get("brand", "").strip()
        model = request.form.get("model", "").strip()
        body_type = request.form.get("body_type", "")
        plate = normalize_plate(request.form.get("plate", ""))
        if _apply_car_fields(car, brand, model, body_type, plate):
            flash("Автомобиль обновлён", "success")
            return redirect(url_for("crm.client_detail", cid=car.client_id))
    return render_template("crm/car_form.html", car=car, body_types=_body_types())


@bp.post("/cars/<int:car_id>/delete")
@login_required
@staff_required
def car_delete(car_id: int):
    car = db.session.get(Car, car_id) or abort(404)
    cid = car.client_id
    log_audit(
        "car.delete",
        entity="car",
        entity_id=car_id,
        details=f"{car.brand} {car.model} {car.plate}",
    )
    db.session.delete(car)
    db.session.commit()
    flash("Автомобиль удалён", "success")
    return redirect(url_for("crm.client_detail", cid=cid))
