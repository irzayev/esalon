"""Schedule: box and employee occupancy calendar."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

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


def _week_range(today_local: datetime, view: str) -> tuple[datetime, datetime]:
    if view == "week":
        start_local = today_local - timedelta(days=today_local.weekday())
        end_local = start_local + timedelta(days=7)
        return start_local, end_local
    start_local = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
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

    start_local, end_local = _week_range(today_local, view)
    date_from = local_to_utc_start(start_local)
    date_to = local_to_utc_start(end_local)

    events = schedule_events(branch_id, date_from, date_to, resource=resource)
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

    branches = get_active_branches()
    return render_template(
        "schedule/index.html",
        events=events,
        resources=resources,
        view=view,
        resource=resource,
        start_date=start_local.strftime("%Y-%m-%d"),
        week_days=week_days,
        week_period_label=week_period_label,
        day_label=start_local.strftime("%d.%m.%Y"),
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

    date_str = request.args.get("date")
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            day = today_local
    else:
        day = today_local

    view = request.args.get("view", "day")
    start_local, end_local = _week_range(day.replace(tzinfo=None) if day.tzinfo else day, view)

    date_from = local_to_utc_start(start_local)
    date_to = local_to_utc_start(end_local)
    events = schedule_events(branch_id, date_from, date_to, resource=resource)
    for ev in events:
        ev["start_local"] = ev["start"][11:16]
        ev["end_local"] = ev["end"][11:16]
    return jsonify({"events": events})
