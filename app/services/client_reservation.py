"""Public client reservation: create NEW orders for manager follow-up."""
from __future__ import annotations

from ..extensions import db
from ..models.branch import Branch
from ..models.client import Car, CarBodyType, Client
from ..models.order import Order, OrderItem, OrderStatus, recalc_order_totals
from ..models.service import Service, ServicePackage, matches_car_body_type
from ..services.chatbot_booking import default_branch, find_or_create_client
from ..utils.audit import log_audit
from ..utils.client_fields import normalize_phone, validate_phone
from ..utils.i18n import translate
from ..utils.order_lookup import next_order_number

_VALID_BODY_TYPES = {t.value for t in CarBodyType}


def _active_services() -> list[Service]:
    return Service.query.filter_by(is_active=True).order_by(Service.name).all()


def _active_packages() -> list[ServicePackage]:
    return (
        ServicePackage.query.filter_by(is_active=True)
        .order_by(ServicePackage.name)
        .all()
    )


def list_offerings_for_body_type(body_type: str | None) -> dict:
    """Services and packages available for the given car body type."""
    services = []
    for svc in _active_services():
        if matches_car_body_type(svc.body_types, body_type):
            services.append(
                {
                    "id": svc.id,
                    "name": svc.name,
                    "description": (svc.description or "").strip(),
                    "price": float(svc.price or 0),
                    "duration_min": int(svc.duration_min or 30),
                }
            )
    packages = []
    for pkg in _active_packages():
        if matches_car_body_type(pkg.body_types, body_type):
            packages.append(
                {
                    "id": pkg.id,
                    "name": pkg.name,
                    "description": (pkg.description or "").strip(),
                    "price": float(pkg.price or 0),
                    "duration_min": int(pkg.duration_min),
                }
            )
    return {"services": services, "packages": packages}


def _resolve_car_for_body_type(client: Client, body_type: str) -> Car:
    car = Car.query.filter_by(client_id=client.id, body_type=body_type).first()
    if car:
        return car
    car = Car(client_id=client.id, body_type=body_type)
    db.session.add(car)
    db.session.flush()
    return car


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


def create_reservation(
    *,
    phone: str,
    body_type: str,
    service_ids: list[int],
    package_id: int | None,
) -> tuple[Order | None, str | None]:
    """Create a NEW order from the public reservation form."""
    normalized = normalize_phone(phone)
    ok, _ = validate_phone(normalized)
    if not ok:
        return None, "reservation.error.phone"

    if body_type not in _VALID_BODY_TYPES:
        return None, "reservation.error.body_type"

    has_services = bool(service_ids)
    has_package = bool(package_id)
    if has_services and has_package:
        return None, "reservation.error.mixed_selection"
    if not has_services and not has_package:
        return None, "reservation.error.no_selection"

    branch = default_branch()
    if not branch:
        return None, "reservation.error.no_branch"

    client = find_or_create_client(normalized, name=translate("reservation.client_default_name"))
    if not client:
        return None, "reservation.error.phone"

    car = _resolve_car_for_body_type(client, body_type)

    order = Order(
        client_id=client.id,
        car_id=car.id,
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
        if not pkg or not pkg.is_active or not matches_car_body_type(pkg.body_types, body_type):
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
            if not svc or not svc.is_active or not matches_car_body_type(svc.body_types, body_type):
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
    log_audit(
        "order.create",
        entity="order",
        entity_id=order.id,
        details=f"#{order.number} · reservation · {client.phone} · {body_type}",
    )
    db.session.commit()
    return order, None
