from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from ...extensions import db
from ...models.employee import Employee, Salary
from ...models.user import User, Role
from ...services.payroll import build_payroll_row, parse_period
from ...utils.branches import effective_branch_id
from ...utils.decorators import manager_required
from ...utils.worker import employee_in_progress_order

bp = Blueprint("employees", __name__)


@bp.route("/")
@login_required
@manager_required
def index():
    items = Employee.query.order_by(Employee.name).all()
    occupancy = {}
    for e in items:
        if not e.is_active:
            occupancy[e.id] = {"busy": False, "order": None}
            continue
        busy_order = employee_in_progress_order(e.id)
        occupancy[e.id] = {"busy": busy_order is not None, "order": busy_order}
    return render_template("employees/index.html", items=items, occupancy=occupancy)


@bp.route("/payroll")
@login_required
@manager_required
def payroll():
    period_start, period_end = parse_period(request.args.get("from"), request.args.get("to"))
    branch_id = effective_branch_id(request, current_user)
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    rows = [build_payroll_row(emp, period_start, period_end, branch_id) for emp in employees]

    existing = (
        Salary.query.filter(
            Salary.period_start == period_start,
            Salary.period_end == period_end,
        )
        .order_by(Salary.created_at.desc())
        .all()
    )
    by_emp = {s.employee_id: s for s in existing}
    for row in rows:
        row["existing_salary"] = by_emp.get(row["employee"].id)

    totals = {
        "base": round(sum(r["base"] for r in rows), 2),
        "bonus": round(sum(r["bonus"] for r in rows), 2),
        "total": round(sum(r["total"] for r in rows), 2),
    }
    return render_template(
        "employees/payroll.html",
        rows=rows,
        period_start=period_start,
        period_end=period_end,
        totals=totals,
        existing=existing,
    )


@bp.post("/payroll/generate")
@login_required
@manager_required
def payroll_generate():
    period_start, period_end = parse_period(request.form.get("from"), request.form.get("to"))
    branch_id = effective_branch_id(request, current_user)
    employees = Employee.query.filter_by(is_active=True).all()

    for emp in employees:
        row = build_payroll_row(emp, period_start, period_end, branch_id)
        salary = Salary.query.filter_by(
            employee_id=emp.id,
            period_start=period_start,
            period_end=period_end,
        ).first()
        if not salary:
            salary = Salary(employee_id=emp.id, period_start=period_start, period_end=period_end)
            db.session.add(salary)

        salary.base = row["base"]
        salary.bonus = row["bonus"]
        salary.total = row["total"]
        salary.visits_count = row["visits_count"]
        salary.revenue_total = row["revenue_total"]
        salary.kpi_score = row["kpi_score"]
        salary.note = row["note"]

    db.session.commit()
    flash("Ведомость за период сформирована", "success")
    params = {"from": period_start.isoformat(), "to": period_end.isoformat()}
    if branch_id:
        params["branch_id"] = branch_id
    return redirect(url_for("employees.payroll", **params))


@bp.post("/payroll/<int:sid>/toggle-paid")
@login_required
@manager_required
def payroll_toggle_paid(sid: int):
    salary = db.session.get(Salary, sid) or abort(404)
    salary.paid = not salary.paid
    salary.paid_at = datetime.utcnow() if salary.paid else None
    db.session.commit()
    flash("Статус выплаты обновлён", "success")
    params = {"from": salary.period_start.isoformat(), "to": salary.period_end.isoformat()}
    bid = effective_branch_id(request, current_user)
    if bid:
        params["branch_id"] = bid
    return redirect(url_for("employees.payroll", **params))


@bp.route("/new", methods=["GET", "POST"])
@login_required
@manager_required
def new():
    if request.method == "POST":
        emp = Employee()
        if _save(emp):
            return redirect(url_for("employees.index"))
        worker_users, taken_user_ids = _worker_user_options()
        return render_template(
            "employees/form.html",
            emp=emp,
            worker_users=worker_users,
            taken_user_ids=taken_user_ids,
        )
    worker_users, taken_user_ids = _worker_user_options()
    return render_template(
        "employees/form.html",
        emp=None,
        worker_users=worker_users,
        taken_user_ids=taken_user_ids,
    )


@bp.route("/<int:eid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def edit(eid: int):
    e = db.session.get(Employee, eid) or abort(404)
    if request.method == "POST":
        if _save(e):
            return redirect(url_for("employees.index"))
        worker_users, taken_user_ids = _worker_user_options(e)
        return render_template(
            "employees/form.html",
            emp=e,
            worker_users=worker_users,
            taken_user_ids=taken_user_ids,
        )
    worker_users, taken_user_ids = _worker_user_options(e)
    return render_template(
        "employees/form.html",
        emp=e,
        worker_users=worker_users,
        taken_user_ids=taken_user_ids,
    )


@bp.post("/<int:eid>/delete")
@login_required
@manager_required
def delete(eid: int):
    e = db.session.get(Employee, eid) or abort(404)
    db.session.delete(e)
    db.session.commit()
    return redirect(url_for("employees.index"))


def _worker_user_options(emp: Employee | None = None) -> tuple[list[User], set[int]]:
    taken: set[int] = set()
    for row in Employee.query.filter(Employee.user_id.isnot(None)).all():
        if emp and row.id == emp.id:
            continue
        if row.user_id:
            taken.add(row.user_id)
    users = User.query.filter_by(role=Role.WORKER, is_active=True).order_by(User.name).all()
    return users, taken


def _save(e: Employee) -> bool:
    f = request.form
    e.name = f.get("name", "").strip()
    e.phone = f.get("phone", "").strip()
    e.position = f.get("position", "").strip()
    e.salary_model = f.get("salary_model", "percent")
    e.base_salary = float(f.get("base_salary") or 0)
    e.percent = float(f.get("percent") or 0)
    e.kpi_target_visits = int(f.get("kpi_target_visits") or 0)
    e.kpi_bonus_per_visit = float(f.get("kpi_bonus_per_visit") or 0)
    e.kpi_target_revenue = float(f.get("kpi_target_revenue") or 0)
    e.kpi_bonus_revenue_percent = float(f.get("kpi_bonus_revenue_percent") or 0)
    e.is_active = bool(f.get("is_active"))

    uid_raw = (f.get("user_id") or "").strip()
    if uid_raw:
        uid = int(uid_raw)
        conflict = Employee.query.filter(
            Employee.user_id == uid,
            Employee.id != (e.id or 0),
        ).first()
        if conflict:
            flash("Этот пользователь уже привязан к другому сотруднику", "error")
            return False
        e.user_id = uid
    else:
        e.user_id = None

    if not e.id:
        db.session.add(e)
    db.session.commit()
    flash("Сотрудник сохранён", "success")
    return True

