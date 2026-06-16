"""Box and employee schedule: slot bounds, conflicts, calendar events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

# Used only if the IANA tz database is unavailable on the host (keeps the
# app working instead of crashing or silently showing raw UTC).
_FALLBACK_TZ = timezone(timedelta(hours=4))  # Asia/Baku (UTC+4, no DST)

from ..extensions import db
from sqlalchemy.orm import joinedload

from ..models.cabinet import Cabinet, CabinetType
from ..models.branch import Branch
from ..models.employee import Employee
from ..models.order import Order, OrderStatus
from ..models.order_assignment import OrderAssignment
from ..models.service import Service
from ..models.settings import Settings

DEFAULT_SLOT_MINUTES = 60
SCHEDULE_SLOT_MINUTES = 30


def default_slot_minutes() -> int:
    """Default reservation length from settings (fallback 60)."""
    raw = Settings.get().default_reservation_minutes
    try:
        mins = int(raw if raw is not None else DEFAULT_SLOT_MINUTES)
    except (TypeError, ValueError):
        mins = DEFAULT_SLOT_MINUTES
    return max(15, mins)


def service_duration_scheduling_enabled() -> bool:
    return bool(Settings.get().schedule_use_service_duration)


DEFAULT_WORK_OPEN = "08:00"
DEFAULT_WORK_CLOSE = "20:00"
ACTIVE_STATUSES = (
    OrderStatus.NEW,
    OrderStatus.BOOKED,
    OrderStatus.DONE,
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


def _time_to_minutes(time_str: str | None, default_hour: int, default_minute: int = 0) -> int:
    normalized = normalize_time_24(time_str)
    if not normalized:
        return default_hour * 60 + default_minute
    hour, minute = normalized.split(":")
    return int(hour) * 60 + int(minute)


def minutes_to_time_label(total_minutes: int) -> str:
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def floor_to_slot_minutes(total_minutes: int, step: int = SCHEDULE_SLOT_MINUTES) -> int:
    return (total_minutes // step) * step


def branch_timeline_bounds(branch: Branch | None) -> tuple[int, int]:
    """First and last schedule slot (minutes from midnight, inclusive)."""
    if branch:
        start = _time_to_minutes(getattr(branch, "work_open", None), 8, 0)
        end = _time_to_minutes(getattr(branch, "work_close", None), 20, 0)
    else:
        start, end = 8 * 60, 20 * 60
    if start > end:
        start, end = end, start
    return start, end


def iter_timeline_slot_labels(
    start_min: int,
    end_min: int,
    *,
    step: int = SCHEDULE_SLOT_MINUTES,
) -> list[str]:
    return [minutes_to_time_label(m) for m in range(start_min, end_min + 1, step)]


def _iso_to_local_minutes(iso: str) -> int | None:
    if len(iso) < 16:
        return None
    try:
        return int(iso[11:13]) * 60 + int(iso[14:16])
    except ValueError:
        return None


def event_timeline_slot(start_iso: str, *, step: int = SCHEDULE_SLOT_MINUTES) -> str | None:
    start_min = _iso_to_local_minutes(start_iso)
    if start_min is None:
        return None
    return minutes_to_time_label(floor_to_slot_minutes(start_min, step))


def event_timeline_slots(
    start_iso: str,
    end_iso: str,
    *,
    bounds_start: int,
    bounds_end: int,
    step: int = SCHEDULE_SLOT_MINUTES,
) -> list[str]:
    """All 30-min slot labels overlapping [start, end)."""
    start_min = _iso_to_local_minutes(start_iso)
    if start_min is None:
        return []
    end_min = _iso_to_local_minutes(end_iso)
    if end_min is None or end_min <= start_min:
        end_min = start_min + step

    slot_start = floor_to_slot_minutes(start_min, step)
    slots: list[str] = []
    m = slot_start
    while m < end_min:
        if m + step > start_min and bounds_start <= m <= bounds_end:
            slots.append(minutes_to_time_label(m))
        m += step
    if not slots and bounds_start <= slot_start <= bounds_end:
        slots.append(minutes_to_time_label(slot_start))
    return slots


def event_duration_minutes(start_iso: str, end_iso: str) -> int:
    start_min = _iso_to_local_minutes(start_iso)
    end_min = _iso_to_local_minutes(end_iso)
    if start_min is None:
        return SCHEDULE_SLOT_MINUTES
    if end_min is None or end_min <= start_min:
        return SCHEDULE_SLOT_MINUTES
    return max(SCHEDULE_SLOT_MINUTES, end_min - start_min)


def minutes_to_timeline_px(minutes: int, slot_row_px: int) -> float:
    return minutes * (slot_row_px / SCHEDULE_SLOT_MINUTES)


def event_timeline_position(
    start_iso: str,
    end_iso: str,
    *,
    bounds_start: int,
    total_height_px: int,
    slot_row_px: int,
) -> dict[str, int] | None:
    """Pixel top/height for a stretched card inside the day timeline."""
    start_min = _iso_to_local_minutes(start_iso)
    if start_min is None:
        return None
    end_min = _iso_to_local_minutes(end_iso)
    if end_min is None or end_min <= start_min:
        end_min = start_min + SCHEDULE_SLOT_MINUTES

    top_px = minutes_to_timeline_px(max(0, start_min - bounds_start), slot_row_px)
    height_px = minutes_to_timeline_px(end_min - start_min, slot_row_px)
    min_h = max(36, int(slot_row_px * 0.45))
    height_px = max(height_px, min_h)
    if top_px + height_px > total_height_px:
        height_px = max(min_h, total_height_px - top_px)
    if top_px >= total_height_px:
        return None
    return {"top_px": round(top_px), "height_px": round(height_px)}


def _event_interval_minutes(ev: dict) -> tuple[int, int] | None:
    start_min = _iso_to_local_minutes(ev.get("start", ""))
    if start_min is None:
        return None
    end_min = _iso_to_local_minutes(ev.get("end", ""))
    if end_min is None or end_min <= start_min:
        end_min = start_min + SCHEDULE_SLOT_MINUTES
    return start_min, end_min


def _intervals_overlap_minutes(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def assign_timeline_lanes(events: list[dict], *, gap_pct: float = 1.0) -> list[dict]:
    """Split overlapping events into side-by-side lanes within each overlap group."""
    items: list[tuple[int, int, dict]] = []
    for ev in events:
        interval = _event_interval_minutes(ev)
        if interval is None:
            continue
        items.append((interval[0], interval[1], ev))

    if not items:
        return events

    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _intervals_overlap_minutes(items[i][0], items[i][1], items[j][0], items[j][1]):
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(items)):
        clusters.setdefault(find(i), []).append(i)

    laid_out: list[dict] = []
    for indices in clusters.values():
        cluster_items = [items[i] for i in indices]
        cluster_items.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        lanes: list[list[int]] = []
        for local_idx, (start, end, _ev) in enumerate(cluster_items):
            lane_idx = None
            for li, lane in enumerate(lanes):
                if any(
                    _intervals_overlap_minutes(
                        start,
                        end,
                        cluster_items[other][0],
                        cluster_items[other][1],
                    )
                    for other in lane
                ):
                    continue
                lane_idx = li
                break
            if lane_idx is None:
                lane_idx = len(lanes)
                lanes.append([])
            lanes[lane_idx].append(local_idx)

        lane_count = max(1, len(lanes))
        usable = 100.0 - gap_pct * (lane_count - 1)
        width_pct = usable / lane_count

        for lane_idx, lane in enumerate(lanes):
            for local_idx in lane:
                _start, _end, ev = cluster_items[local_idx]
                laid_out.append({
                    **ev,
                    "lane_index": lane_idx,
                    "lane_count": lane_count,
                    "lane_width_pct": round(width_pct, 4),
                    "lane_left_pct": round(lane_idx * (width_pct + gap_pct), 4),
                })

    laid_out.sort(key=lambda e: (e.get("top_px", 0), e.get("lane_index", 0), e.get("start", "")))
    return laid_out


def slot_has_booking(slot_min: int, events: list[dict]) -> bool:
    """True if any event overlaps this 30-minute slot."""
    slot_end = slot_min + SCHEDULE_SLOT_MINUTES
    for ev in events:
        start_min = _iso_to_local_minutes(ev.get("start", ""))
        if start_min is None:
            continue
        end_min = _iso_to_local_minutes(ev.get("end", ""))
        if end_min is None or end_min <= start_min:
            end_min = start_min + SCHEDULE_SLOT_MINUTES
        if start_min < slot_end and end_min > slot_min:
            return True
    return False


def branch_work_hours(branch: Branch | None) -> tuple[str, str]:
    if not branch:
        return DEFAULT_WORK_OPEN, DEFAULT_WORK_CLOSE
    open_t = normalize_time_24(getattr(branch, "work_open", None)) or DEFAULT_WORK_OPEN
    close_t = normalize_time_24(getattr(branch, "work_close", None)) or DEFAULT_WORK_CLOSE
    return open_t, close_t


def time_within_branch_hours(time_str: str, branch: Branch | None) -> bool:
    normalized = normalize_time_24(time_str)
    if not normalized:
        return False
    start_min, end_min = branch_timeline_bounds(branch)
    hour, minute = normalized.split(":")
    slot_min = floor_to_slot_minutes(int(hour) * 60 + int(minute))
    return start_min <= slot_min <= end_min


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


def _sum_service_duration_minutes(order: Order) -> int:
    total = 0
    for item in order.items:
        if item.service_id:
            svc = db.session.get(Service, item.service_id)
            if svc and svc.duration_min:
                total += int(svc.duration_min * (item.qty or 1))
        elif item.package_id and item.package:
            total += int(item.package.duration_min * (item.qty or 1))
    return total


def order_duration_minutes(order: Order, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = default_slot_minutes()
    if not service_duration_scheduling_enabled():
        return fallback
    total = _sum_service_duration_minutes(order)
    return total or fallback


def reserved_duration_minutes(order: Order) -> int:
    if not (order.scheduled_at and order.scheduled_end_at):
        return 0
    return int((order.scheduled_end_at - order.scheduled_at).total_seconds() // 60)


def reservation_schedule_mismatch(order: Order) -> dict[str, int] | None:
    """When service-duration scheduling is on and saved slot differs from services."""
    if not service_duration_scheduling_enabled():
        return None
    reserved = reserved_duration_minutes(order)
    if reserved <= 0:
        return None
    services = order_duration_minutes(order)
    if services == reserved:
        return None
    return {"reserved": reserved, "services": services}


def order_scheduled_duration_minutes(order: Order) -> int:
    """Saved slot length, or estimate from services, or default from settings."""
    if order.scheduled_at and order.scheduled_end_at:
        mins = reserved_duration_minutes(order)
        if mins > 0:
            return mins
    if not service_duration_scheduling_enabled():
        return default_slot_minutes()
    return order_duration_minutes(order)


def recalc_order_schedule_end_from_services(order: Order) -> str | None:
    """Set scheduled_end_at from service durations. Returns error code or None."""
    if not order.scheduled_at:
        return "no_schedule"
    duration = order_duration_minutes(order)
    end = order.scheduled_at + timedelta(minutes=duration)
    if order.cabinet_id and cabinet_has_conflict(
        order.cabinet_id,
        order.scheduled_at,
        end,
        exclude_order_id=order.id,
    ):
        return "conflict"
    order.scheduled_end_at = end
    return None


def order_required_cabinet_types(order: Order) -> set[str]:
    from ..models.service import ServicePackage

    required: set[str] = set()
    for item in order.items:
        if item.package_id:
            pkg = db.session.get(ServicePackage, item.package_id)
            if pkg:
                required.update(pkg.resolve_required_cabinet_types())
            continue
        if not item.service_id:
            continue
        svc = db.session.get(Service, item.service_id)
        if svc and svc.required_cabinet_type:
            required.add(svc.required_cabinet_type)
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

    if order.scheduled_at:
        start = order.scheduled_at
        end = compute_scheduled_end(order, start)
        return start, end

    if order.cabinet_id and order.started_at:
        start = order.started_at
        end = order.completed_at or (start + timedelta(minutes=order_duration_minutes(order)))
        return start, end

    return None, None


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def cabinet_has_conflict(
    cabinet_id: int,
    start: datetime,
    end: datetime,
    *,
    exclude_order_id: int | None = None,
) -> bool:
    q = Order.query.filter(
        Order.cabinet_id == cabinet_id,
        Order.status != OrderStatus.CANCELED,
        Order.cabinet_id.isnot(None),
    )
    if exclude_order_id:
        q = q.filter(Order.id != exclude_order_id)
    for other in q.all():
        o_start, o_end = order_slot_bounds(other)
        if o_start and o_end and intervals_overlap(start, end, o_start, o_end):
            return True
    return False


def compatible_cabinets(
    branch_id: int,
    required_types: set[str],
    start: datetime,
    end: datetime,
    *,
    exclude_order_id: int | None = None,
) -> list[Cabinet]:
    bays = (
        Cabinet.query.filter_by(branch_id=branch_id, is_active=True)
        .order_by(Cabinet.sort_order, Cabinet.id)
        .all()
    )
    result = []
    for bay in bays:
        if not bay.supports_types(required_types):
            continue
        if cabinet_has_conflict(bay.id, start, end, exclude_order_id=exclude_order_id):
            continue
        result.append(bay)
    return result


def suggest_cabinet(order: Order, start: datetime, end: datetime | None = None) -> Cabinet | None:
    if not order.branch_id:
        return None
    end = end or (start + timedelta(minutes=order_duration_minutes(order)))
    bays = compatible_cabinets(
        order.branch_id,
        order_required_cabinet_types(order),
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
    cabinet_id: int | None,
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

    if cabinet_id is not None:
        bay = db.session.get(Cabinet, cabinet_id)
        if not bay:
            return "Бокс не найден"
        if order.branch_id is None:
            order.branch_id = bay.branch_id
        elif bay.branch_id != order.branch_id:
            return "Бокс принадлежит другому филиалу"
        required = order_required_cabinet_types(order)
        if required and not bay.supports_types(required):
            return "Бокс не подходит под тип услуг в заказе"
        start, end = order_slot_bounds(order)
        if not start and scheduled_at:
            start, end = scheduled_at, order.scheduled_end_at
        if start and end and cabinet_has_conflict(bay.id, start, end, exclude_order_id=order.id):
            return "Бокс занят в выбранное время"
        order.cabinet_id = cabinet_id

    return None


def occupy_cabinet_now(order: Order, cabinet_id: int) -> str | None:
    """Walk-in: assign bay and mark in progress from now."""
    bay = db.session.get(Cabinet, cabinet_id)
    if not bay:
        return "Бокс не найден"
    if order.branch_id is None:
        order.branch_id = bay.branch_id
    elif bay.branch_id != order.branch_id:
        return "Бокс принадлежит другому филиалу"
    required = order_required_cabinet_types(order)
    if required and not bay.supports_types(required):
        return "Бокс не подходит под тип услуг в заказе"
    now = datetime.utcnow()
    dur = order_duration_minutes(order)
    end = now + timedelta(minutes=dur)
    if cabinet_has_conflict(cabinet_id, now, end, exclude_order_id=order.id):
        return "Бокс занят сейчас"
    order.cabinet_id = cabinet_id
    order.started_at = now
    order.scheduled_at = now
    order.scheduled_end_at = end
    if order.status == OrderStatus.NEW:
        order.status = OrderStatus.BOOKED
    return None


def _order_event_title(order: Order) -> str:
    client = order.client.name if order.client else ""
    parts = [f"#{order.number}"]
    if client:
        parts.append(client)
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

    return {
        "id": order.id,
        "number": order.number,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_label": resource_label,
        "title": _order_event_title(order),
        "client_name": order.client.name if order.client else "",
        "services_summary": _order_services_summary(order),
        "start": start_iso,
        "end": end_iso,
        "date": start_iso[:10] if start_iso else "",
        "start_hour": int(start_iso[11:13]) if len(start_iso) >= 13 else 0,
        "timeline_slot": event_timeline_slot(start_iso) or "",
        "duration_minutes": event_duration_minutes(start_iso, end_iso),
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
    resource: str = "cabinet",
    include_canceled: bool = False,
) -> list[dict[str, Any]]:
    """Calendar events between date_from and date_to (UTC naive, inclusive start)."""
    events: list[dict[str, Any]] = []
    q = Order.query
    if not include_canceled:
        q = q.filter(Order.status != OrderStatus.CANCELED)
    if branch_id:
        q = q.filter(Order.branch_id == branch_id)

    if resource == "cabinet":
        q = q.filter(Order.cabinet_id.isnot(None))
    elif resource == "employee":
        assigned_ids = db.session.query(OrderAssignment.order_id).distinct()
        q = q.filter(Order.id.in_(assigned_ids))
    else:
        return events

    q = q.options(
        joinedload(Order.client),
        joinedload(Order.cabinet),
        joinedload(Order.items),
        joinedload(Order.assignments).joinedload(OrderAssignment.employee),
    )

    for order in q.all():
        start, end = order_slot_bounds(order)
        if not start or not end:
            continue
        if end <= date_from or start >= date_to:
            continue

        if resource == "cabinet" and order.cabinet:
            events.append(
                _order_event_payload(
                    order,
                    resource_type="cabinet",
                    resource_id=order.cabinet_id,
                    resource_label=order.cabinet.name,
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


def active_cabinets_for_branch(branch_id: int) -> list[Cabinet]:
    return (
        Cabinet.query.filter_by(branch_id=branch_id, is_active=True)
        .order_by(Cabinet.sort_order, Cabinet.id)
        .all()
    )
