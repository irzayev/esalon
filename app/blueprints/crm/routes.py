from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from ...extensions import db
from ...models.client import Client, ClientLevel
from ...models.order import Order, VISIT_STATUSES
from ...models.wa_chat_session import WaChatSession
from ...models.wa_message import WaMessage
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
    parse_birthday,
)
from ...models.bonus import BonusWallet, BonusTransaction
from ...utils.pagination import (
    LIST_PER_PAGE_CHOICES,
    list_page,
    list_per_page,
    pagination_page_numbers,
)

bp = Blueprint("crm", __name__)

_CLIENT_SORT_KEYS = frozenset(
    {
        "name",
        "phone",
        "level",
        "visits_count",
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
    visits_count = (
        select(Order.client_id, func.count(Order.id).label("visits_count"))
        .where(Order.status.in_(VISIT_STATUSES))
        .group_by(Order.client_id)
        .subquery()
    )
    return last_visit, orders_count, avg_check, visits_count


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

    last_visit_sq, orders_count_sq, avg_check_sq, visits_count_sq = _client_list_subqueries()

    query = (
        Client.query.outerjoin(last_visit_sq, Client.id == last_visit_sq.c.client_id)
        .outerjoin(orders_count_sq, Client.id == orders_count_sq.c.client_id)
        .outerjoin(avg_check_sq, Client.id == avg_check_sq.c.client_id)
        .outerjoin(visits_count_sq, Client.id == visits_count_sq.c.client_id)
        .add_columns(
            last_visit_sq.c.last_visit_at,
            func.coalesce(orders_count_sq.c.orders_count, 0).label("orders_count_val"),
            func.coalesce(avg_check_sq.c.avg_check, 0.0).label("avg_check_val"),
            func.coalesce(visits_count_sq.c.visits_count, 0).label("visits_count_val"),
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
        "visits_count": func.coalesce(visits_count_sq.c.visits_count, 0),
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
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page = list_page(request.args.get("page"), total_pages)
    offset = (page - 1) * per_page

    items = []
    for client, last_visit_at, orders_count_val, avg_check_val, visits_count_val in (
        query.order_by(order, tiebreaker).offset(offset).limit(per_page).all()
    ):
        client.visit_at = last_visit_at
        client.list_orders_count = int(orders_count_val or 0)
        client.list_avg_check = float(avg_check_val or 0)
        client.list_visits_count = int(visits_count_val or 0)
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
                form=request.form,
            )
        return redirect(url_for("crm.client_detail", cid=c.id))
    return render_template(
        "crm/client_form.html",
        client=None,
        levels=list(ClientLevel),
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
                form=request.form,
            )
        return redirect(url_for("crm.client_detail", cid=c.id))
    return render_template(
        "crm/client_form.html",
        client=c,
        levels=list(ClientLevel),
        form=None,
    )


def _purge_client_dependencies(client_id: int) -> None:
    """Remove CRM data tied to a client (kept when operational reset runs)."""
    session_ids = [
        row[0]
        for row in WaChatSession.query.filter_by(client_id=client_id)
        .with_entities(WaChatSession.id)
        .all()
    ]
    if session_ids:
        WaMessage.query.filter(WaMessage.session_id.in_(session_ids)).delete(
            synchronize_session=False
        )
    WaMessage.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    WaChatSession.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    BonusTransaction.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    BonusWallet.query.filter_by(client_id=client_id).delete(synchronize_session=False)


@bp.post("/clients/<int:cid>/delete")
@login_required
@staff_required
def client_delete(cid: int):
    c = db.session.get(Client, cid) or abort(404)
    order_count = Order.query.filter_by(client_id=c.id).count()
    if order_count:
        flash(
            f"Нельзя удалить клиента: есть связанные заказы ({order_count}).",
            "error",
        )
        return redirect(url_for("crm.client_detail", cid=c.id))
    try:
        _purge_client_dependencies(c.id)
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


from . import chats_routes  # noqa: F401, E402 — register /crm/chats/*
