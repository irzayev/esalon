from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from ...extensions import db
from ...models.cash_expense import CashExpense
from ...services.report_queries import cash_export_sections, load_cash_day
from ...services.table_export import send_excel
from ...utils.branches import effective_branch_id, resolve_order_branch_id
from ...utils.decorators import manager_required
from ...utils.i18n import translate

bp = Blueprint("finance", __name__)


def _parse_day() -> tuple:
    date_str = request.args.get("date") or request.form.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        day = datetime.utcnow().date()
    branch_id = effective_branch_id(request, current_user)
    return day, branch_id


def _redirect_finance(day) -> str:
    return url_for("finance.index", date=day.isoformat())


def _assert_expense_access(expense) -> None:
    pass


def _parse_amount(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        amount = float(str(raw).replace(",", ".").strip())
    except ValueError:
        return None
    if amount <= 0:
        return None
    return round(amount, 2)


@bp.route("/")
@login_required
@manager_required
def index():
    day, branch_id = _parse_day()
    data = load_cash_day(day, branch_id)
    return render_template(
        "finance/index.html",
        day=data["day"],
        by_method=data["by_method"],
        total=data["total"],
        payments=data["payments"],
        expenses=data["expenses"],
        expenses_total=data["expenses_total"],
        net_total=data["net_total"],
        export_params=_export_query(day, branch_id),
    )


def _export_query(day, branch_id) -> dict:
    return {"date": day.isoformat()}


@bp.post("/expenses")
@login_required
@manager_required
def expense_create():
    day, branch_id = _parse_day()
    name = (request.form.get("name") or "").strip()
    amount = _parse_amount(request.form.get("amount"))
    if not name:
        flash(translate("flash.expense_name_required"), "error")
        return redirect(_redirect_finance(day))
    if amount is None:
        flash(translate("flash.expense_amount_invalid"), "error")
        return redirect(_redirect_finance(day))

    expense = CashExpense(
        name=name,
        amount=amount,
        expense_date=day,
        branch_id=branch_id or resolve_order_branch_id(request, current_user),
    )
    db.session.add(expense)
    db.session.commit()
    flash(translate("flash.expense_saved"), "success")
    return redirect(_redirect_finance(day))


@bp.route("/expenses/<int:eid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def expense_edit(eid: int):
    expense = db.session.get(CashExpense, eid) or abort(404)
    _assert_expense_access(expense)
    day = expense.expense_date

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        amount = _parse_amount(request.form.get("amount"))
        if not name:
            flash(translate("flash.expense_name_required"), "error")
            return redirect(url_for("finance.expense_edit", eid=eid, date=day.isoformat()))
        if amount is None:
            flash(translate("flash.expense_amount_invalid"), "error")
            return redirect(url_for("finance.expense_edit", eid=eid, date=day.isoformat()))

        expense.name = name
        expense.amount = amount
        db.session.commit()
        flash(translate("flash.expense_saved"), "success")
        return redirect(_redirect_finance(day))

    return render_template(
        "finance/expense_form.html",
        expense=expense,
        day=day,
        export_params=_export_query(day, effective_branch_id(request, current_user)),
    )


@bp.post("/expenses/<int:eid>/delete")
@login_required
@manager_required
def expense_delete(eid: int):
    expense = db.session.get(CashExpense, eid) or abort(404)
    _assert_expense_access(expense)
    day = expense.expense_date
    db.session.delete(expense)
    db.session.commit()
    flash(translate("flash.expense_deleted"), "success")
    return redirect(_redirect_finance(day))


@bp.get("/export.xlsx")
@login_required
@manager_required
def export_excel():
    day, branch_id = _parse_day()
    data = load_cash_day(day, branch_id)
    sections = cash_export_sections(data)
    sheets = [
        {
            "name": (s.get("title") or "Касса")[:31],
            "headers": s.get("headers"),
            "rows": s.get("rows"),
            "summary_rows": s.get("summary_rows"),
        }
        for s in sections
    ]
    return send_excel(f"cash-{day.isoformat()}.xlsx", sheets)
