"""Schedule: box and employee occupancy calendar."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from ...extensions import db
from ...models.order import Order, OrderStatus
from ...models.user import Role
from ...services.scheduling import (
    app_timezone,
    schedule_events,
    active_bays_for_branch,
    local_to_utc_start,
    parse_schedule_datetime,
    apply_order_schedule,
    order_scheduled_duration_minutes,
    suggest_bay,
    branch_timeline_bounds,
    iter_timeline_slot_labels,
    event_timeline_position,
    assign_timeline_lanes,
    slot_has_booking,
    minutes_to_timeline_px,
    SCHEDULE_SLOT_MINUTES,
    time_within_branch_hours,
)
from ...utils.audit import format_status_change, log_audit
from ...utils.branches import branch_id_for_bays, get_active_branches
from ...utils.decorators import staff_required
from ...utils.i18n import order_status_label, translate

bp = Blueprint("schedule", __name__)

_WEEKDAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

BOOKABLE_SLOT_STATUSES = (
    OrderStatus.NEW,
    OrderStatus.BOOKED,
    OrderStatus.WAITING,
    OrderStatus.IN_PROGRESS,
)

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


def _parse_filter_id(raw: str | None, valid_ids: set[int]) -> int | None:
    if not raw:
        return None
    try:
        filter_id = int(raw)
    except ValueError:
        return None
    return filter_id if filter_id in valid_ids else None


def _filter_resources(resources: list[dict], filter_id: int | None) -> list[dict]:
    if filter_id is None:
        return resources
    return [res for res in resources if res["id"] == filter_id]


def _schedule_nav_kwargs(
    *,
    view: str,
    resource: str,
    branch_id: int | None,
    status_filter: str,
    filter_id: int | None,
) -> dict:
    kwargs: dict = {"view": view, "resource": resource}
    if branch_id:
        kwargs["branch_id"] = branch_id
    if status_filter:
        kwargs["status"] = status_filter
    if filter_id is not None:
        kwargs["filter_id"] = filter_id
    return kwargs


def _schedule_index_url(base: dict, **overrides) -> str:
    kwargs = dict(base)
    for key, value in overrides.items():
        if value is None or value == "":
            kwargs.pop(key, None)
        else:
            kwargs[key] = value
    return url_for("schedule.index", **kwargs)


BAY_SLOT_ROW_PX = 88
EMPLOYEE_SLOT_ROW_PX = 80


def _build_timeline_view(
    events: list[dict],
    start_min: int,
    end_min: int,
    slot_row_px: int,
) -> dict:
    """Day timeline: slot grid + absolutely positioned stretched booking cards."""
    slot_labels = iter_timeline_slot_labels(start_min, end_min)
    slot_count = len(slot_labels)
    total_height_px = slot_count * slot_row_px

    positioned: list[dict] = []
    for ev in events:
        pos = event_timeline_position(
            ev.get("start", ""),
            ev.get("end", ""),
            bounds_start=start_min,
            total_height_px=total_height_px,
            slot_row_px=slot_row_px,
        )
        if pos:
            positioned.append({**ev, **pos})
    positioned = assign_timeline_lanes(positioned)

    empty_slots = []
    for index, label in enumerate(slot_labels):
        slot_min = start_min + index * SCHEDULE_SLOT_MINUTES
        if not slot_has_booking(slot_min, events):
            empty_slots.append({
                "label": label,
                "top_px": round(minutes_to_timeline_px(slot_min - start_min, slot_row_px)),
            })

    return {
        "slots": [{"label": label, "index": i} for i, label in enumerate(slot_labels)],
        "events": positioned,
        "empty_slots": empty_slots,
        "total_height_px": total_height_px,
        "slot_row_px": slot_row_px,
    }


def _build_time_axis(start_min: int, end_min: int, slot_row_px: int) -> dict:
    slot_labels = iter_timeline_slot_labels(start_min, end_min)
    return {
        "slots": [{"label": label, "index": i} for i, label in enumerate(slot_labels)],
        "total_height_px": len(slot_labels) * slot_row_px,
        "slot_row_px": slot_row_px,
    }


def _build_day_grid(
    resources: list[dict],
    events: list[dict],
    start_min: int,
    end_min: int,
    slot_row_px: int,
) -> dict:
    """Day view: shared time axis + one column per bay or employee."""
    return {
        "time_axis": _build_time_axis(start_min, end_min, slot_row_px),
        "columns": [
            {
                "id": res["id"],
                "label": res["label"],
                "timeline": _build_timeline_view(
                    [e for e in events if e.get("resource_id") == res["id"]],
                    start_min,
                    end_min,
                    slot_row_px,
                ),
            }
            for res in resources
        ],
    }


def _now_timeline_marker(
    today_local: datetime,
    day_local: datetime,
    start_min: int,
    end_min: int,
    slot_row_px: int,
) -> dict | None:
    if day_local.date() != today_local.date():
        return None
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    if not (start_min <= now_min <= end_min + SCHEDULE_SLOT_MINUTES):
        return None
    return {
        "time_label": now.strftime("%H:%M"),
        "top_px": round(minutes_to_timeline_px(now_min - start_min, slot_row_px)),
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
    all_resources: list[dict] = []
    if resource == "bay" and branch_id:
        all_resources = [{"id": b.id, "label": b.name} for b in active_bays_for_branch(branch_id)]
    elif resource == "employee":
        from ...models.employee import Employee

        employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
        all_resources = [{"id": e.id, "label": e.name} for e in employees]

    valid_resource_ids = {res["id"] for res in all_resources}
    filter_id = _parse_filter_id(request.args.get("filter_id"), valid_resource_ids)
    resources = _filter_resources(all_resources, filter_id)

    week_days = _build_week_days(start_local) if view == "week" else []
    week_end_label = (start_local + timedelta(days=6)).strftime("%d.%m.%Y")
    week_period_label = f"{start_local.strftime('%d.%m')} — {week_end_label}"

    prev_day = (day_local - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (day_local + timedelta(days=1)).strftime("%Y-%m-%d")
    is_today = day_local.date() == today_local.date()

    branches = get_active_branches()
    current_branch = next((b for b in branches if b.id == branch_id), None) if branch_id else None
    if branch_id and not current_branch:
        from ...models.branch import Branch
        current_branch = db.session.get(Branch, branch_id)
    timeline_start, timeline_end = branch_timeline_bounds(current_branch)

    slot_row_px = EMPLOYEE_SLOT_ROW_PX if resource == "employee" else BAY_SLOT_ROW_PX
    day_grid = (
        _build_day_grid(resources, events, timeline_start, timeline_end, slot_row_px)
        if view == "day" and resources
        else None
    )
    now_marker = (
        _now_timeline_marker(today_local, day_local, timeline_start, timeline_end, slot_row_px)
        if view == "day"
        else None
    )

    schedule_nav = _schedule_nav_kwargs(
        view=view,
        resource=resource,
        branch_id=branch_id,
        status_filter=status_filter,
        filter_id=filter_id,
    )

    def schedule_url(**overrides):
        return _schedule_index_url(schedule_nav, **overrides)

    status_filters = [
        {
            "value": st.value if st else "",
            "label_key": label_key,
            "active": (status_filter == (st.value if st else "")),
            "url": schedule_url(status=(st.value if st else None)),
        }
        for st, label_key in _STATUS_FILTERS
    ]
    resource_filters = [
        {
            "id": None,
            "label_key": "common.all",
            "active": filter_id is None,
            "url": schedule_url(filter_id=None),
        },
        *[
            {
                "id": res["id"],
                "label": res["label"],
                "active": filter_id == res["id"],
                "url": schedule_url(filter_id=res["id"]),
            }
            for res in all_resources
        ],
    ]

    return render_template(
        "schedule/index.html",
        events=events,
        resources=resources,
        all_resources=all_resources,
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
        day_grid=day_grid,
        now_marker=now_marker,
        status_filter=status_filter,
        status_filters=status_filters,
        filter_id=filter_id,
        resource_filters=resource_filters,
        schedule_url=schedule_url,
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


@bp.get("/api/schedule/bookable-orders")
@login_required
@staff_required
def api_bookable_orders():
    from flask_login import current_user
    from sqlalchemy.orm import joinedload

    branch_id = branch_id_for_bays(request, current_user)
    q = (
        Order.query.options(joinedload(Order.client), joinedload(Order.car))
        .filter(Order.status.in_(BOOKABLE_SLOT_STATUSES))
        .order_by(Order.updated_at.desc(), Order.created_at.desc())
    )
    if branch_id:
        q = q.filter(Order.branch_id == branch_id)

    rows = []
    for order in q.limit(100).all():
        lbl, cls = order_status_label(order.status)
        rows.append({
            "number": order.number,
            "client_name": order.client.name if order.client else "",
            "car_title": order.car.display if order.car else "",
            "status": order.status,
            "status_label": lbl,
            "status_class": cls,
        })
    return jsonify({"orders": rows})


def _schedule_return_url() -> str:
    args = {
        k: v
        for k, v in {
            "view": request.form.get("view") or request.args.get("view", "day"),
            "resource": request.form.get("resource") or request.args.get("resource", "bay"),
            "branch_id": request.form.get("branch_id") or request.args.get("branch_id"),
            "date": request.form.get("schedule_date") or request.args.get("date"),
            "status": request.form.get("status") or request.args.get("status"),
            "filter_id": request.form.get("filter_id") or request.args.get("filter_id"),
        }.items()
        if v
    }
    return url_for("schedule.index", **args)


@bp.post("/schedule/assign-slot")
@login_required
@staff_required
def assign_slot():
    from ...models.employee import Employee
    from ...services.order_assignees import add_order_assignee

    order_number = (request.form.get("order_number") or "").strip()
    schedule_date = (request.form.get("schedule_date") or "").strip()
    schedule_time = (request.form.get("schedule_time") or "").strip()
    resource = (request.form.get("resource") or "bay").strip()
    employee_id_raw = (request.form.get("employee_id") or "").strip()

    order = Order.query.filter_by(number=order_number).first()
    if not order:
        flash("Заказ не найден", "error")
        return redirect(_schedule_return_url())

    if order.status not in BOOKABLE_SLOT_STATUSES:
        flash(translate("schedule.slot_no_orders"), "error")
        return redirect(_schedule_return_url())

    scheduled_at = parse_schedule_datetime(schedule_date, schedule_time)
    if not scheduled_at:
        flash(translate("schedule.slot_invalid_time"), "error")
        return redirect(_schedule_return_url())

    from ...models.branch import Branch

    schedule_branch = order.branch
    if not schedule_branch and order.branch_id:
        schedule_branch = db.session.get(Branch, order.branch_id)
    if not schedule_branch:
        branch_id_raw = request.form.get("branch_id") or request.args.get("branch_id")
        if branch_id_raw:
            try:
                schedule_branch = db.session.get(Branch, int(branch_id_raw))
            except ValueError:
                pass
    if schedule_branch and not time_within_branch_hours(schedule_time, schedule_branch):
        flash(translate("schedule.slot_outside_hours"), "error")
        return redirect(_schedule_return_url())

    duration = order_scheduled_duration_minutes(order)
    end = scheduled_at + timedelta(minutes=duration)
    old_status = order.status
    set_booked = order.status == OrderStatus.NEW

    if resource == "employee":
        if not employee_id_raw:
            flash(translate("schedule.slot_need_employee"), "error")
            return redirect(_schedule_return_url())
        try:
            employee_id = int(employee_id_raw)
        except ValueError:
            flash(translate("schedule.slot_need_employee"), "error")
            return redirect(_schedule_return_url())

        employee = db.session.get(Employee, employee_id)
        if not employee or not employee.is_active:
            flash(translate("schedule.slot_need_employee"), "error")
            return redirect(_schedule_return_url())

        add_order_assignee(order, employee_id)

        bay_id = order.bay_id
        if not bay_id:
            suggested = suggest_bay(order, scheduled_at, end)
            bay_id = suggested.id if suggested else None

        if bay_id:
            err = apply_order_schedule(
                order,
                bay_id=int(bay_id),
                scheduled_at=scheduled_at,
                duration_min=duration,
                set_booked=set_booked,
            )
            if err:
                flash(err, "error")
                return redirect(_schedule_return_url())
        else:
            order.scheduled_at = scheduled_at
            order.scheduled_end_at = end
            if set_booked and order.status == OrderStatus.NEW:
                order.status = OrderStatus.BOOKED

        log_audit(
            "order.assign",
            entity="order",
            entity_id=order.id,
            details=f"#{order.number}: {employee.name}",
        )
        log_audit(
            "order.schedule",
            entity="order",
            entity_id=order.id,
            details=f"#{order.number} · {schedule_date} {schedule_time}",
        )
    else:
        bay_id_raw = (request.form.get("bay_id") or "").strip()
        bay_id = None
        if bay_id_raw:
            try:
                bay_id = int(bay_id_raw)
            except ValueError:
                pass
        if not bay_id:
            bay_id = order.bay_id
        if not bay_id:
            suggested = suggest_bay(order, scheduled_at, end)
            bay_id = suggested.id if suggested else None
        if not bay_id:
            flash(translate("schedule.slot_need_bay"), "error")
            return redirect(url_for("orders.detail", number=order.number))

        err = apply_order_schedule(
            order,
            bay_id=int(bay_id),
            scheduled_at=scheduled_at,
            duration_min=duration,
            set_booked=set_booked,
        )
        if err:
            flash(err, "error")
            return redirect(_schedule_return_url())

        log_audit(
            "order.schedule",
            entity="order",
            entity_id=order.id,
            details=f"#{order.number} · {schedule_date} {schedule_time}",
        )

    if old_status != order.status:
        from ...services.order_work_time import sync_order_work_timer

        sync_order_work_timer(order, old_status, order.status)
        log_audit(
            "order.status",
            entity="order",
            entity_id=order.id,
            details=format_status_change(old_status, order.status),
        )
    db.session.commit()
    flash(
        translate("schedule.slot_assigned_employee")
        if resource == "employee"
        else translate("schedule.slot_assigned"),
        "success",
    )
    return redirect(_schedule_return_url())
