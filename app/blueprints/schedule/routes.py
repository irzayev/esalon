"""Schedule: box and employee occupancy calendar."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from ...models.user import Role
from ...services.scheduling import (
    app_timezone,
    schedule_events,
    utc_naive_to_local,
    active_bays_for_branch,
    local_to_utc_start,
)
from ...utils.branches import effective_branch_id, get_active_branches
from ...utils.decorators import staff_required

bp = Blueprint("schedule", __name__)


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
    branch_id = effective_branch_id(request, current_user)

    if view == "week":
        start_local = today_local - timedelta(days=today_local.weekday())
        end_local = start_local + timedelta(days=7)
    else:
        start_local = today_local
        end_local = start_local + timedelta(days=1)

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

    branches = get_active_branches()
    return render_template(
        "schedule/index.html",
        events=events,
        resources=resources,
        view=view,
        resource=resource,
        start_date=start_local.strftime("%Y-%m-%d"),
        branches=branches,
        branch_id=branch_id,
    )


@bp.get("/api/schedule/events")
@login_required
@staff_required
def api_events():
    from flask_login import current_user

    branch_id = effective_branch_id(request, current_user)
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
    if view == "week":
        start_local = day - timedelta(days=day.weekday())
        end_local = start_local + timedelta(days=7)
    else:
        start_local = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)

    date_from = local_to_utc_start(start_local)
    date_to = local_to_utc_start(end_local)
    events = schedule_events(branch_id, date_from, date_to, resource=resource)
    for ev in events:
        start = datetime.fromisoformat(ev["start"])
        end = datetime.fromisoformat(ev["end"])
        ev["start_local"] = utc_naive_to_local(start).strftime("%H:%M") if utc_naive_to_local(start) else ""
        ev["end_local"] = utc_naive_to_local(end).strftime("%H:%M") if utc_naive_to_local(end) else ""
    return jsonify({"events": events})
