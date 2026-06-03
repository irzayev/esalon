"""Box and employee schedule: slot bounds, conflicts, calendar events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

# Used only if the IANA tz database is unavailable on the host (keeps the
# app working instead of crashing or silently showing raw UTC).
_FALLBACK_TZ = timezone(timedelta(hours=4))  # Asia/Baku (UTC+4, no DST)

from ..extensions import db
from ..models.bay import Bay, BayType
from ..models.employee import Employee
from ..models.order import Order, OrderStatus
from ..models.order_assignment import OrderAssignment
from ..models.service import Service
from ..models.settings import Settings

DEFAULT_SLOT_MINUTES = 60
ACTIVE_STATUSES = (
    OrderStatus.NEW,
    OrderStatus.BOOKED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.WAITING,
    OrderStatus.DONE,
    OrderStatus.DELIVERED,
)


def app_timezone() -> tzinfo:
    tz_name = (Settings.get().timezone or "Asia/Baku").strip() or "Asia/Baku"
    for name in (tz_name, "Asia/Baku"):
        try:
            return ZoneInfo(name)
        except Exception:
            continue
    return _FALLBACK_TZ


def local_to_utc_start(d: datetime) -> datetime:
    """Start of local calendar day as UTC naive."""
    local_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_to_utc_naive(local_start)


def local_to_utc_naive(dt_local: datetime) -> datetime:
    """Store as UTC naive (matches started_at / created_at convention)."""
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=app_timezone())
    return dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def utc_naive_to_local(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(app_timezone()).replace(tzinfo=None)


def normalize_time_24(time_str: str | None) -> str | None:
    """Parse user time to HH:MM (24-hour). Accepts 14:30, 1430, 9:5."""
    if not time_str:
        return None
    raw = time_str.strip()
    if not raw:
        return None
    if ":" in raw:
        parts = raw.split(":", 1)
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            return None
    elif raw.isdigit():
        if len(raw) <= 2:
            h, m = int(raw), 0
        elif len(raw) == 3:
            h, m = int(raw[0]), int(raw[1:])
        else:
            h, m = int(raw[:-2]), int(raw[-2:])
    else:
        return None
    if h < 0 or h > 23 or m < 0 or m > 59:
        return None
    return f"{h:02d}:{m:02d}"


def parse_schedule_datetime(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str or not time_str:
        return None
    t = normalize_time_24(time_str)
    if not t:
        return None
    try:
        local = datetime.strptime(f"{date_str.strip()} {t}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return local_to_utc_naive(local)


def order_duration_minutes(order: Order, fallback: int = DEFAULT_SLOT_MINUTES) -> int:
    total = 0
    for item in order.items:
        if item.service_id:
            svc = db.session.get(Service, item.service_id)
            if svc and svc.duration_min:
                total += int(svc.duration_min * (item.qty or 1))
        elif item.package_id and item.package:
            for svc in item.package.services:
                total += int((svc.duration_min or 30) * (item.qty or 1))
    return total or fallback


def order_scheduled_duration_minutes(order: Order) -> int:
    """Saved slot length, or estimate from services, or default 60."""
    if order.scheduled_at and order.scheduled_end_at:
        mins = int((order.scheduled_end_at - order.scheduled_at).total_seconds() // 60)
        if mins > 0:
            return mins
    return order_duration_minutes(order)


def order_required_bay_types(order: Order) -> set[str]:
    required: set[str] = set()
    for item in order.items:
        if not item.service_id:
            continue
        svc = db.session.get(Service, item.service_id)
        if svc and svc.required_bay_type:
            required.add(svc.required_bay_type)
    return required


def compute_scheduled_end(order: Order, start: datetime | None = None) -> datetime | None:
    start = start or order.scheduled_at
    if not start:
        return None
    if order.scheduled_end_at and (not start or order.scheduled_at == start):
        return order.scheduled_end_at
    return start + timedelta(minutes=order_scheduled_duration_minutes(order))


def order_slot_bounds(order: Order) -> tuple[datetime | None, datetime | None]:
    """Return (start, end) UTC naive for calendar display."""
    if order.status == OrderStatus.CANCELED:
        return None, None

    if order.status == OrderStatus.IN_PROGRESS and order.started_at:
        start = order.started_at
        end = order.completed_at or (start + timedelta(minutes=order_duration_minutes(order)))
        return start, end

    if order.scheduled_at:
        start = order.scheduled_at
        end = compute_scheduled_end(order, start)
        return start, end

    if order.bay_id and order.started_at:
        start = order.started_at
        end = order.completed_at or (start + timedelta(minutes=order_duration_minutes(order)))
        return start, end

    return None, None


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def bay_has_conflict(
    bay_id: int,
    start: datetime,
    end: datetime,
    *,
    exclude_order_id: int | None = None,
) -> bool:
    q = Order.query.filter(
        Order.bay_id == bay_id,
        Order.status != OrderStatus.CANCELED,
        Order.bay_id.isnot(None),
    )
    if exclude_order_id:
        q = q.filter(Order.id != exclude_order_id)
    for other in q.all():
        o_start, o_end = order_slot_bounds(other)
        if o_start and o_end and intervals_overlap(start, end, o_start, o_end):
            return True
    return False


def compatible_bays(
    branch_id: int,
    required_types: set[str],
    start: datetime,
    end: datetime,
    *,
    exclude_order_id: int | None = None,
) -> list[Bay]:
    bays = (
        Bay.query.filter_by(branch_id=branch_id, is_active=True)
        .order_by(Bay.sort_order, Bay.id)
        .all()
    )
    result = []
    for bay in bays:
        if not bay.supports_types(required_types):
            continue
        if bay_has_conflict(bay.id, start, end, exclude_order_id=exclude_order_id):
            continue
        result.append(bay)
    return result


def suggest_bay(order: Order, start: datetime, end: datetime | None = None) -> Bay | None:
    if not order.branch_id:
        return None
    end = end or (start + timedelta(minutes=order_duration_minutes(order)))
    bays = compatible_bays(
        order.branch_id,
        order_required_bay_types(order),
        start,
        end,
        exclude_order_id=order.id,
    )
    return bays[0] if bays else None


def sync_order_schedule_end(order: Order) -> None:
    if order.scheduled_at and not order.scheduled_end_at:
        order.scheduled_end_at = compute_scheduled_end(order)


def apply_order_schedule(
    order: Order,
    *,
    bay_id: int | None,
    scheduled_at: datetime | None,
    duration_min: int | None = None,
    set_booked: bool = False,
) -> str | None:
    """Apply bay/time to order. Returns error message or None on success."""
    if scheduled_at:
        dur = duration_min or order_scheduled_duration_minutes(order)
        end = scheduled_at + timedelta(minutes=dur)
        order.scheduled_at = scheduled_at
        order.scheduled_end_at = end
        if set_booked and order.status == OrderStatus.NEW:
            order.status = OrderStatus.BOOKED
    elif duration_min and order.scheduled_at:
        order.scheduled_end_at = order.scheduled_at + timedelta(minutes=duration_min)

    if bay_id is not None:
        bay = db.session.get(Bay, bay_id)
        if not bay:
            return "Бокс не найден"
        if order.branch_id is None:
            order.branch_id = bay.branch_id
        elif bay.branch_id != order.branch_id:
            return "Бокс принадлежит другому филиалу"
        required = order_required_bay_types(order)
        if required and not bay.supports_types(required):
            return "Бокс не подходит под тип услуг в заказе"
        start, end = order_slot_bounds(order)
        if not start and scheduled_at:
            start, end = scheduled_at, order.scheduled_end_at
        if start and end and bay_has_conflict(bay.id, start, end, exclude_order_id=order.id):
            return "Бокс занят в выбранное время"
        order.bay_id = bay_id

    return None


def occupy_bay_now(order: Order, bay_id: int) -> str | None:
    """Walk-in: assign bay and mark in progress from now."""
    bay = db.session.get(Bay, bay_id)
    if not bay:
        return "Бокс не найден"
    if order.branch_id is None:
        order.branch_id = bay.branch_id
    elif bay.branch_id != order.branch_id:
        return "Бокс принадлежит другому филиалу"
    required = order_required_bay_types(order)
    if required and not bay.supports_types(required):
        return "Бокс не подходит под тип услуг в заказе"
    now = datetime.utcnow()
    dur = order_duration_minutes(order)
    end = now + timedelta(minutes=dur)
    if bay_has_conflict(bay_id, now, end, exclude_order_id=order.id):
        return "Бокс занят сейчас"
    order.bay_id = bay_id
    order.started_at = now
    order.scheduled_at = now
    order.scheduled_end_at = end
    if order.status in (OrderStatus.NEW, OrderStatus.BOOKED):
        old_status = order.status
        order.status = OrderStatus.IN_PROGRESS
        from .order_work_time import sync_order_work_timer

        sync_order_work_timer(order, old_status, OrderStatus.IN_PROGRESS)
    return None


def _order_event_title(order: Order) -> str:
    car = order.car.display if order.car else ""
    parts = [f"#{order.number}"]
    if car:
        parts.append(car)
    return " · ".join(parts)


def _order_services_summary(order: Order, max_items: int = 2) -> str:
    names: list[str] = []
    for item in order.items:
        label = (item.name or "").strip()
        if label:
            names.append(label)
        if len(names) >= max_items:
            break
    if not names:
        return ""
    summary = ", ".join(names[:max_items])
    extra = len(order.items) - len(names)
    if extra > 0:
        summary += f" +{extra}"
    return summary


def _order_event_payload(order: Order, *, resource_type: str, resource_id: int, resource_label: str) -> dict[str, Any]:
    from ..utils.i18n import order_status_label
    from ..i18n.order_status_styles import ORDER_STATUS_COLORS

    start, end = order_slot_bounds(order)
    start_iso = (utc_naive_to_local(start) or start).isoformat() if start else ""
    end_iso = (utc_naive_to_local(end) or end).isoformat() if end else ""
    status_lbl, status_cls = order_status_label(order.status)
    accent_bg, _accent_fg = ORDER_STATUS_COLORS.get(order.status, ("#94a3b8", "#334155"))

    car = order.car
    car_title = ""
    if car:
        parts = [p for p in [car.brand, car.model] if p]
        car_title = " ".join(parts) or car.display

    return {
        "id": order.id,
        "number": order.number,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_label": resource_label,
        "title": _order_event_title(order),
        "car_title": car_title,
        "client_name": order.client.name if order.client else "",
        "services_summary": _order_services_summary(order),
        "start": start_iso,
        "end": end_iso,
        "date": start_iso[:10] if start_iso else "",
        "start_hour": int(start_iso[11:13]) if len(start_iso) >= 13 else 0,
        "status": order.status,
        "status_label": status_lbl,
        "status_class": status_cls,
        "status_accent": accent_bg,
        "url": f"/orders/{order.number}",
    }


def schedule_events(
    branch_id: int | None,
    date_from: datetime,
    date_to: datetime,
    *,
    resource: str = "bay",
    include_canceled: bool = False,
) -> list[dict[str, Any]]:
    """Calendar events between date_from and date_to (UTC naive, inclusive start)."""
    events: list[dict[str, Any]] = []
    q = Order.query
    if not include_canceled:
        q = q.filter(Order.status != OrderStatus.CANCELED)
    if branch_id:
        q = q.filter(Order.branch_id == branch_id)

    if resource == "bay":
        q = q.filter(Order.bay_id.isnot(None))
    elif resource == "employee":
        assigned_ids = db.session.query(OrderAssignment.order_id).distinct()
        q = q.filter(Order.id.in_(assigned_ids))
    else:
        return events

    from sqlalchemy.orm import joinedload

    from ..models.order_assignment import OrderAssignment

    q = q.options(
        joinedload(Order.client),
        joinedload(Order.car),
        joinedload(Order.bay),
        joinedload(Order.items),
        joinedload(Order.assignments).joinedload(OrderAssignment.employee),
    )

    for order in q.all():
        start, end = order_slot_bounds(order)
        if not start or not end:
            continue
        if end <= date_from or start >= date_to:
            continue

        if resource == "bay" and order.bay:
            events.append(
                _order_event_payload(
                    order,
                    resource_type="bay",
                    resource_id=order.bay_id,
                    resource_label=order.bay.name,
                )
            )
        elif resource == "employee":
            for assignment in order.assignments:
                emp = assignment.employee
                if not emp:
                    continue
                events.append(
                    _order_event_payload(
                        order,
                        resource_type="employee",
                        resource_id=emp.id,
                        resource_label=emp.name,
                    )
                )

    events.sort(key=lambda e: (e["start"], e.get("resource_label", "")))
    return events


def active_bays_for_branch(branch_id: int) -> list[Bay]:
    return (
        Bay.query.filter_by(branch_id=branch_id, is_active=True)
        .order_by(Bay.sort_order, Bay.id)
        .all()
    )
