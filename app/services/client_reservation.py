"""Public client reservation: create NEW orders for manager follow-up."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..extensions import db
from ..models.client import Client
from ..models.order import Order, OrderItem, OrderStatus, recalc_order_totals
from ..models.service import Service, ServicePackage
from ..services.chatbot_booking import available_slots, default_branch, find_client_by_phone, find_or_create_client
from ..services.scheduling import (
    apply_order_schedule,
    compatible_cabinets,
    default_slot_minutes,
    parse_schedule_datetime,
    service_duration_scheduling_enabled,
    utc_naive_to_local,
)
from ..utils.audit import log_audit
from ..utils.client_fields import normalize_phone, validate_phone, validate_reservation_phone_local
from ..utils.i18n import translate
from ..utils.order_lookup import next_order_number


def _active_services() -> list[Service]:
    return (
        Service.query.filter_by(is_active=True, client_reservable=True)
        .order_by(Service.name)
        .all()
    )


def _active_packages() -> list[ServicePackage]:
    return (
        ServicePackage.query.filter_by(is_active=True, client_reservable=True)
        .order_by(ServicePackage.name)
        .all()
    )


def list_offerings() -> dict:
    """Active services and packages available for online booking."""
    services = [
        {
            "id": svc.id,
            "name": svc.name,
            "description": (svc.description or "").strip(),
            "price": float(svc.price or 0),
            "duration_min": int(svc.duration_min or 30),
        }
        for svc in _active_services()
    ]
    packages = [
        {
            "id": pkg.id,
            "name": pkg.name,
            "description": (pkg.description or "").strip(),
            "price": float(pkg.price or 0),
            "duration_min": int(pkg.duration_min),
        }
        for pkg in _active_packages()
    ]
    return {"services": services, "packages": packages}


def _local_today() -> date:
    now = utc_naive_to_local(datetime.utcnow())
    return (now or datetime.utcnow()).date()


def _parse_schedule_date(raw: str | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _validate_selection(
    service_ids: list[int],
    package_id: int | None,
) -> str | None:
    has_services = bool(service_ids)
    has_package = bool(package_id)
    if has_services and has_package:
        return "reservation.error.mixed_selection"
    if not has_services and not has_package:
        return "reservation.error.no_selection"
    if package_id:
        pkg = db.session.get(ServicePackage, package_id)
        if not pkg or not pkg.is_active or not pkg.client_reservable:
            return "reservation.error.invalid_package"
    else:
        for sid in service_ids:
            svc = db.session.get(Service, sid)
            if not svc or not svc.is_active or not svc.client_reservable:
                return "reservation.error.invalid_service"
    return None


def required_cabinet_types_for_selection(
    package_id: int | None,
    service_ids: list[int],
) -> set[str]:
    required: set[str] = set()
    if package_id:
        pkg = db.session.get(ServicePackage, package_id)
        if pkg:
            return pkg.resolve_required_cabinet_types()
        return required
    for sid in service_ids:
        svc = db.session.get(Service, sid)
        if svc and svc.required_cabinet_type:
            required.add(svc.required_cabinet_type)
    return required


def duration_for_selection(package_id: int | None, service_ids: list[int]) -> int:
    if not service_duration_scheduling_enabled():
        return default_slot_minutes()
    if package_id:
        pkg = db.session.get(ServicePackage, package_id)
        if pkg:
            return int(pkg.duration_min)
    total = 0
    for sid in service_ids:
        svc = db.session.get(Service, sid)
        if svc:
            total += int(svc.duration_min or 30)
    return total or default_slot_minutes()


def list_slots_for_selection(
    *,
    service_ids: list[int],
    package_id: int | None,
    day: date,
) -> tuple[list[dict] | None, str | None]:
    err = _validate_selection(service_ids, package_id)
    if err:
        return None, err
    if day < _local_today():
        return None, "reservation.error.past_date"

    branch = default_branch()
    if not branch:
        return None, "reservation.error.no_branch"

    duration = duration_for_selection(package_id, service_ids)
    required_types = required_cabinet_types_for_selection(package_id, service_ids)
    slots = available_slots(branch.id, day, duration, required_types)
    if day == _local_today():
        now_utc = datetime.utcnow()
        slots = [slot for slot in slots if slot.scheduled_at > now_utc]
    return (
        [
            {
                "time": slot.time_label,
                "cabinet_id": slot.cabinet_id,
                "date": slot.date_str,
            }
            for slot in slots
        ],
        None,
    )


def _find_matching_slot(
    *,
    service_ids: list[int],
    package_id: int | None,
    schedule_date: str,
    schedule_time: str,
    cabinet_id: int,
) -> tuple[datetime | None, int | None, int | None, str | None]:
    day = _parse_schedule_date(schedule_date)
    if not day:
        return None, None, None, "reservation.error.invalid_slot"
    slots, err = list_slots_for_selection(
        service_ids=service_ids,
        package_id=package_id,
        day=day,
    )
    if err:
        return None, None, None, err
    time_label = (schedule_time or "").strip()
    for slot in slots or []:
        if slot["time"] == time_label and int(slot["cabinet_id"]) == cabinet_id:
            scheduled_at = parse_schedule_datetime(schedule_date, time_label)
            if not scheduled_at:
                return None, None, None, "reservation.error.invalid_slot"
            duration = duration_for_selection(package_id, service_ids)
            end_at = scheduled_at + timedelta(minutes=duration)
            cabinets = compatible_cabinets(
                default_branch().id,
                required_cabinet_types_for_selection(package_id, service_ids),
                scheduled_at,
                end_at,
            )
            if not any(c.id == cabinet_id for c in cabinets):
                return None, None, None, "reservation.error.slot_taken"
            return scheduled_at, cabinet_id, duration, None
    return None, None, None, "reservation.error.invalid_slot"


def _parse_service_ids(raw_values: list[str]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid > 0 and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def lookup_client_by_phone(
    phone: str, *, phone_local: str | None = None
) -> tuple[Client | None, str | None]:
    """Return existing client for a normalized phone, or None if not found."""
    if phone_local is not None and not validate_reservation_phone_local(phone_local):
        return None, "reservation.error.phone"
    normalized = normalize_phone(phone)
    ok, _ = validate_phone(normalized)
    if not ok:
        return None, "reservation.error.phone"
    return find_client_by_phone(normalized), None


def create_reservation(
    *,
    phone: str,
    phone_local: str | None = None,
    client_name: str | None = None,
    service_ids: list[int],
    package_id: int | None,
    schedule_date: str,
    schedule_time: str,
    cabinet_id: int | None,
) -> tuple[Order | None, str | None]:
    """Create a NEW order from the public reservation form."""
    if phone_local is not None and not validate_reservation_phone_local(phone_local):
        return None, "reservation.error.phone"
    normalized = normalize_phone(phone)
    ok, _ = validate_phone(normalized)
    if not ok:
        return None, "reservation.error.phone"

    selection_err = _validate_selection(service_ids, package_id)
    if selection_err:
        return None, selection_err

    if not schedule_date or not schedule_time or not cabinet_id:
        return None, "reservation.error.no_slot"

    scheduled_at, validated_cabinet_id, duration_min, slot_err = _find_matching_slot(
        service_ids=service_ids,
        package_id=package_id,
        schedule_date=schedule_date,
        schedule_time=schedule_time,
        cabinet_id=int(cabinet_id),
    )
    if slot_err:
        return None, slot_err

    branch = default_branch()
    if not branch:
        return None, "reservation.error.no_branch"

    existing = find_client_by_phone(normalized)
    if existing:
        client = find_or_create_client(normalized, name=(client_name or "").strip())
    else:
        name = (client_name or "").strip()
        if not name:
            return None, "reservation.error.client_name"
        client = find_or_create_client(normalized, name=name)
    if not client:
        return None, "reservation.error.phone"

    order = Order(
        client_id=client.id,
        branch_id=branch.id,
        status=OrderStatus.NEW.value,
        notes=translate("reservation.order_note"),
    )
    try:
        order.number = next_order_number()
    except ValueError:
        return None, "reservation.error.number_conflict"

    db.session.add(order)
    db.session.flush()

    if package_id:
        pkg = db.session.get(ServicePackage, package_id)
        if not pkg or not pkg.is_active or not pkg.client_reservable:
            db.session.rollback()
            return None, "reservation.error.invalid_package"
        db.session.add(
            OrderItem(
                order_id=order.id,
                package_id=pkg.id,
                name=f"{translate('reservation.package_prefix')}: {pkg.name}",
                price=pkg.price,
                qty=1,
            )
        )
    else:
        for sid in service_ids:
            svc = db.session.get(Service, sid)
            if not svc or not svc.is_active or not svc.client_reservable:
                db.session.rollback()
                return None, "reservation.error.invalid_service"
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    service_id=svc.id,
                    name=svc.name,
                    price=svc.price,
                    qty=1,
                )
            )

    recalc_order_totals(order)

    schedule_err = apply_order_schedule(
        order,
        cabinet_id=validated_cabinet_id,
        scheduled_at=scheduled_at,
        duration_min=duration_min,
        set_booked=False,
    )
    if schedule_err:
        db.session.rollback()
        return None, "reservation.error.slot_taken"

    log_audit(
        "order.create",
        entity="order",
        entity_id=order.id,
        details=f"#{order.number} · reservation · {client.phone}",
    )
    db.session.commit()
    return order, None
