from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from ...services.report_queries import (
    load_period_report,
    parse_date_range,
    reports_export_sections,
)
from ...services.table_export import send_excel
from ...utils.branches import effective_branch_id
from ...utils.decorators import manager_required

bp = Blueprint("reports", __name__)


def _query_params(period_start, period_end, branch_id) -> dict:
    params = {"from": period_start.isoformat(), "to": period_end.isoformat()}
    if branch_id:
        params["branch_id"] = branch_id
    return params


@bp.route("/")
@login_required
@manager_required
def index():
    period_start, period_end = parse_date_range(
        request.args.get("from"),
        request.args.get("to"),
    )
    branch_id = effective_branch_id(request, current_user)
    report = load_period_report(period_start, period_end, branch_id)
    return render_template(
        "reports/index.html",
        report=report,
        period_start=period_start,
        period_end=period_end,
        export_params=_query_params(period_start, period_end, branch_id),
    )


@bp.get("/export.xlsx")
@login_required
@manager_required
def export_excel():
    period_start, period_end = parse_date_range(
        request.args.get("from"),
        request.args.get("to"),
    )
    branch_id = effective_branch_id(request, current_user)
    report = load_period_report(period_start, period_end, branch_id)
    sections = reports_export_sections(report)
    sheets = [
        {
            "name": s.get("title", "Лист")[:31],
            "headers": s.get("headers"),
            "rows": s.get("rows"),
            "summary_rows": s.get("summary_rows"),
        }
        for s in sections
    ]
    return send_excel(
        f"report-{period_start.isoformat()}-{period_end.isoformat()}.xlsx",
        sheets,
    )
