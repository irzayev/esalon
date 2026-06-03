"""Schedule: box and employee occupancy calendar."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from ...models.order import OrderStatus
from ...models.user import Role
from ...services.scheduling import (
    app_timezone,
    schedule_events,
    active_bays_for_branch,
    local_to_utc_start,
)
from ...utils.branches import branch_id_for_bays, get_active_branches
from ...utils.decorators import staff_required

bp = Blueprint("schedule", __name__)

_WEEKDAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

TIMELINE_START_HOUR = 8
TIMELINE_END_HOUR = 20

_STATUS_FILTERS = (
    ("", "common.all"),
    (OrderStatus.NEW, "order.status.new"),
    (OrderStatus.BOOKED, "order.status.booked"),
    (OrderStatus.IN_PROGRESS, "order.status.in_progress"),
    (OrderStatus.WAITING, "order.status.waiting"),
    (OrderStatus.CANCELED, "order.status.canceled"),
)


def _week_range(day_local: datetime, view: str) -> tuple[datetime, datetime]:
    if view == "week":
        start_local = day_local - timedelta(days=day_local.weekday())
        end_local = start_local + timedelta(days=7)
        return start_local, end_local
    start_local = day_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local, start_local + timedelta(days=1)


def _build_week_days(start_local: datetime) -> list[dict]:
    days = []
    for i in range(7):
        d = start_local + timedelta(days=i)
        days.append({
            "iso": d.strftime("%Y-%m-%d"),
            "label": f"{_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}",
        })
    return days


def _parse_day_local(date_str: str | None, today_local: datetime) -> datetime:
    if not date_str:
        return today_local
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return today_local


def _filter_events(events: list[dict], status_filter: str) -> list[dict]:
    if not status_filter:
        return [e for e in events if e.get("status") != OrderStatus.CANCELED]
    return [e for e in events if e.get("status") == status_filter]


def _build_timeline_blocks(events: list[dict]) -> list[dict]:
    """Hourly rows for day timeline (reference: bookings_management)."""
    by_hour: dict[int, list[dict]] = {h: [] for h in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR + 1)}
    for ev in events:
        h = ev.get("start_hour", 0)
        if TIMELINE_START_HOUR <= h <= TIMELINE_END_HOUR:
            by_hour[h].append(ev)

    blocks = []
    for hour in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR + 1):
        hour_events = sorted(by_hour[hour], key=lambda e: e.get("start", ""))
        blocks.append({
            "hour": f"{hour:02d}:00",
            "events": hour_events,
            "empty": len(hour_events) == 0,
        })
    return blocks


def _now_timeline_marker(today_local: datetime, day_local: datetime) -> dict | None:
    if day_local.date() != today_local.date():
        return None
    now = datetime.now()
    if not (TIMELINE_START_HOUR <= now.hour <= TIMELINE_END_HOUR):
        return None
    return {
        "time_label": now.strftime("%H:%M"),
        "hour": now.hour,
    }


@bp.route("/schedule")
@login_required
@staff_required
def index():
    from flask_login import current_user

    if current_user.role == Role.WORKER:
        from flask import redirect, url_for
        return redirect(url_for("worker.index"))

    tz = app_timezone()
    today_local = datetime.now(tz).replace(tzinfo=None)
    view = request.args.get("view", "day")
    resource = request.args.get("resource", "bay")
    branch_id = branch_id_for_bays(request, current_user)
    status_filter = request.args.get("status", "").strip()

    day_local = _parse_day_local(request.args.get("date"), today_local)
    start_local, end_local = _week_range(day_local, view)
    date_from = local_to_utc_start(start_local)
    date_to = local_to_utc_start(end_local)

    include_canceled = status_filter == OrderStatus.CANCELED
    events = _filter_events(
        schedule_events(
            branch_id,
            date_from,
            date_to,
            resource=resource,
            include_canceled=include_canceled,
        ),
        status_filter,
    )
    resources = []
    if resource == "bay" and branch_id:
        resources = [{"id": b.id, "label": b.name} for b in active_bays_for_branch(branch_id)]
    elif resource == "employee":
        from ...models.employee import Employee

        employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
        resources = [{"id": e.id, "label": e.name} for e in employees]

    week_days = _build_week_days(start_local) if view == "week" else []
    week_end_label = (start_local + timedelta(days=6)).strftime("%d.%m.%Y")
    week_period_label = f"{start_local.strftime('%d.%m')} — {week_end_label}"

    prev_day = (day_local - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (day_local + timedelta(days=1)).strftime("%Y-%m-%d")
    is_today = day_local.date() == today_local.date()

    timeline_blocks = _build_timeline_blocks(events) if view == "day" else []
    now_marker = _now_timeline_marker(today_local, day_local) if view == "day" else None

    status_filters = [
        {
            "value": st.value if st else "",
            "label_key": label_key,
            "active": (status_filter == (st.value if st else "")),
        }
        for st, label_key in _STATUS_FILTERS
    ]

    branches = get_active_branches()
    return render_template(
        "schedule/index.html",
        events=events,
        resources=resources,
        view=view,
        resource=resource,
        start_date=start_local.strftime("%Y-%m-%d"),
        day_local=day_local,
        day_label=day_local.strftime("%d.%m.%Y"),
        prev_day=prev_day,
        next_day=next_day,
        is_today=is_today,
        week_days=week_days,
        week_period_label=week_period_label,
        active_count=len(events),
        timeline_blocks=timeline_blocks,
        now_marker=now_marker,
        status_filter=status_filter,
        status_filters=status_filters,
        branches=branches,
        branch_id=branch_id,
    )


@bp.get("/api/schedule/events")
@login_required
@staff_required
def api_events():
    from flask_login import current_user

    branch_id = branch_id_for_bays(request, current_user)
    resource = request.args.get("resource", "bay")
    tz = app_timezone()
    today_local = datetime.now(tz).replace(tzinfo=None)

    day_local = _parse_day_local(request.args.get("date"), today_local)

    view = request.args.get("view", "day")
    start_local, end_local = _week_range(day_local, view)

    date_from = local_to_utc_start(start_local)
    date_to = local_to_utc_start(end_local)
    status_filter = request.args.get("status", "").strip()
    include_canceled = status_filter == OrderStatus.CANCELED
    events = _filter_events(
        schedule_events(
            branch_id,
            date_from,
            date_to,
            resource=resource,
            include_canceled=include_canceled,
        ),
        status_filter,
    )
    for ev in events:
        ev["start_local"] = ev["start"][11:16]
        ev["end_local"] = ev["end"][11:16]
    return jsonify({"events": events})
