"""Chatbot booking: clients, slots, order creation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from ..extensions import db
from ..models.branch import Branch
from ..models.client import Client
from ..models.order import Order, OrderItem, OrderStatus, recalc_order_totals
from ..models.service import Service, ServicePackage
from ..models.settings import Settings
from ..utils.audit import log_audit
from ..utils.client_fields import normalize_phone, validate_phone
from ..utils.order_lookup import next_order_number
from .scheduling import (
    SCHEDULE_SLOT_MINUTES,
    apply_order_schedule,
    branch_timeline_bounds,
    compatible_bays,
    default_slot_minutes,
    minutes_to_time_label,
    parse_schedule_datetime,
)


@dataclass
class MenuServiceItem:
    kind: str  # service | package
    id: int
    name: str
    price: float
    duration_min: int
    required_bay_types: set[str]


@dataclass
class AvailableSlot:
    index: int
    time_label: str
    scheduled_at: datetime
    bay_id: int
    date_str: str


def phone_from_evolution(raw: str, settings: Settings | None = None) -> str:
    """Convert Evolution digits/JID to E.164 stored in CRM."""
    s = settings or Settings.get()
    digits = re.sub(r"\D", "", (raw or "").split("@")[0])
    if not digits:
        return ""
    cc = (s.evolution_default_country_code or "994").strip()
    if not digits.startswith(cc) and len(digits) <= 10:
        digits = cc + digits.lstrip("0")
    return normalize_phone(f"+{digits}")


def find_client_by_phone(phone: str) -> Client | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    client = Client.query.filter_by(phone=normalized).first()
    if client:
        return client
    digits = re.sub(r"\D", "", normalized)
    if not digits:
        return None
    return Client.query.filter(
        or_(
            Client.phone == normalized,
            Client.phone.like(f"%{digits[-9:]}"),
        )
    ).first()


def find_or_create_client(phone: str, name: str = "") -> Client | None:
    normalized = normalize_phone(phone)
    ok, _ = validate_phone(normalized)
    if not ok:
        return None
    client = find_client_by_phone(normalized)
    if client:
        if name and name.strip() and client.name in ("", "WhatsApp"):
            client.name = name.strip()
        return client
    display_name = (name or "").strip() or "WhatsApp"
    client = Client(name=display_name, phone=normalized)
    db.session.add(client)
    db.session.flush()
    return client


def default_branch() -> Branch | None:
    return (
        Branch.query.filter_by(is_active=True)
        .order_by(Branch.id)
        .first()
    )


def list_services_for_menu() -> list[MenuServiceItem]:
    items: list[MenuServiceItem] = []
    for svc in Service.query.filter_by(is_active=True).order_by(Service.name).all():
        req = {svc.required_bay_type} if svc.required_bay_type else set()
        items.append(
            MenuServiceItem(
                kind="service",
                id=svc.id,
                name=svc.name,
                price=float(svc.price or 0),
                duration_min=int(svc.duration_min or 30),
                required_bay_types=req,
            )
        )
    for pkg in ServicePackage.query.filter_by(is_active=True).order_by(ServicePackage.name).all():
        req: set[str] = set()
        for svc in pkg.services:
            if svc.required_bay_type:
                req.add(svc.required_bay_type)
        items.append(
            MenuServiceItem(
                kind="package",
                id=pkg.id,
                name=f"Пакет: {pkg.name}",
                price=float(pkg.price or 0),
                duration_min=int(pkg.duration_min),
                required_bay_types=req,
            )
        )
    return items


def parse_user_date(text: str) -> date | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _date_to_schedule_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def available_slots(
    branch_id: int,
    day: date,
    duration_min: int,
    required_types: set[str],
) -> list[AvailableSlot]:
    branch = db.session.get(Branch, branch_id)
    if not branch:
        return []
    start_min, end_min = branch_timeline_bounds(branch)
    date_str = _date_to_schedule_str(day)
    result: list[AvailableSlot] = []
    idx = 1
    for slot_min in range(start_min, end_min + 1, SCHEDULE_SLOT_MINUTES):
        end_slot_min = slot_min + duration_min
        if end_slot_min > end_min + SCHEDULE_SLOT_MINUTES:
            continue
        time_label = minutes_to_time_label(slot_min)
        scheduled_at = parse_schedule_datetime(date_str, time_label)
        if not scheduled_at:
            continue
        end_at = scheduled_at + timedelta(minutes=duration_min)
        bays = compatible_bays(branch_id, required_types, scheduled_at, end_at)
        if not bays:
            continue
        result.append(
            AvailableSlot(
                index=idx,
                time_label=time_label,
                scheduled_at=scheduled_at,
                bay_id=bays[0].id,
                date_str=date_str,
            )
        )
        idx += 1
    return result


def format_services_menu(items: list[MenuServiceItem], currency: str) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item.name} — {item.price:.0f} {currency}")
    return "\n".join(lines) if lines else "Нет доступных услуг."


def format_slots_menu(slots: list[AvailableSlot]) -> str:
    return "\n".join(f"{s.index}. {s.time_label}" for s in slots)


def create_booking(
    *,
    phone: str,
    client_name: str,
    item_kind: str,
    item_id: int,
    scheduled_at: datetime,
    bay_id: int,
    duration_min: int,
) -> tuple[Order | None, str | None]:
    """Create booked order. Returns (order, error_message)."""
    client = find_or_create_client(phone, client_name)
    if not client:
        return None, "Некорректный номер телефона"

    branch = default_branch()
    if not branch:
        return None, "Нет активного филиала"

    order = Order(
        client_id=client.id,
        branch_id=branch.id,
        status=OrderStatus.NEW.value,
        notes="Создано через WhatsApp чат-бот",
    )
    try:
        order.number = next_order_number()
    except ValueError as exc:
        return None, str(exc)

    db.session.add(order)
    db.session.flush()

    if item_kind == "service":
        svc = db.session.get(Service, item_id)
        if not svc or not svc.is_active:
            db.session.rollback()
            return None, "Услуга не найдена"
        db.session.add(
            OrderItem(
                order_id=order.id,
                service_id=svc.id,
                name=svc.name,
                price=svc.price,
                qty=1,
            )
        )
    elif item_kind == "package":
        pkg = db.session.get(ServicePackage, item_id)
        if not pkg or not pkg.is_active:
            db.session.rollback()
            return None, "Пакет не найден"
        db.session.add(
            OrderItem(
                order_id=order.id,
                package_id=pkg.id,
                name=f"Пакет: {pkg.name}",
                price=pkg.price,
                qty=1,
            )
        )
    else:
        db.session.rollback()
        return None, "Неизвестный тип услуги"

    db.session.flush()
    dur = duration_min or default_slot_minutes()
    err = apply_order_schedule(
        order,
        bay_id=bay_id,
        scheduled_at=scheduled_at,
        duration_min=dur,
        set_booked=True,
    )
    if err:
        db.session.rollback()
        return None, err

    recalc_order_totals(order)
    log_audit(
        "order.create",
        entity="order",
        entity_id=order.id,
        details=f"#{order.number} · chatbot · {client.phone}",
    )
    db.session.commit()

    return order, None


def format_date_display(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def utc_to_local_time_label(scheduled_at: datetime) -> str:
    from .scheduling import utc_naive_to_local

    local = utc_naive_to_local(scheduled_at)
    if not local:
        return ""
    return local.strftime("%H:%M")
