from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required

from ...extensions import db
from ...models.inventory import (
    DEFAULT_INVENTORY_UNIT,
    INVENTORY_UNITS,
    InventoryItem,
    InventoryMovement,
)
from ...services.report_queries import (
    inventory_export_sheets,
    load_inventory_consumptions,
    load_inventory_stock,
    parse_date_range,
)
from ...services.table_export import send_excel
from ...utils.audit import log_audit
from ...utils.decorators import manager_required, staff_required
from ...utils.list_sort import parse_list_sort, make_toggle_sort_dir

bp = Blueprint("inventory", __name__)

_STOCK_SORT_KEYS = frozenset({"name", "sku", "qty", "min", "cost"})
_WRITEOFF_SORT_KEYS = frozenset({"date", "order", "material", "qty", "cost"})


def _consumption_filters():
    period_start, period_end = parse_date_range(
        request.args.get("from"),
        request.args.get("to"),
    )
    item_id_raw = request.args.get("item_id", "").strip()
    item_filter = int(item_id_raw) if item_id_raw.isdigit() else None
    return period_start, period_end, item_filter


def _export_params(period_start, period_end, item_filter) -> dict:
    params = {"from": period_start.isoformat(), "to": period_end.isoformat()}
    if item_filter:
        params["item_id"] = str(item_filter)
    return params


@bp.route("/")
@login_required
@staff_required
def index():
    sort, direction = parse_list_sort(
        request.args, _STOCK_SORT_KEYS, "name", default_dir="asc"
    )
    wo_sort, wo_direction = parse_list_sort(
        request.args,
        _WRITEOFF_SORT_KEYS,
        "date",
        default_dir="desc",
        sort_key="wo_sort",
        dir_key="wo_dir",
    )

    items = load_inventory_stock(sort=sort, direction=direction)
    period_start, period_end, item_filter = _consumption_filters()
    consumptions, total_cost = load_inventory_consumptions(
        period_start,
        period_end,
        item_filter,
        sort=wo_sort,
        direction=wo_direction,
    )

    list_query = {
        "sort": sort,
        "dir": direction,
        "wo_sort": wo_sort,
        "wo_dir": wo_direction,
        "from": period_start.isoformat(),
        "to": period_end.isoformat(),
    }
    if item_filter:
        list_query["item_id"] = str(item_filter)

    return render_template(
        "inventory/index.html",
        items=items,
        consumptions=consumptions,
        period_start=period_start,
        period_end=period_end,
        item_filter=item_filter,
        total_cost=total_cost,
        export_params=_export_params(period_start, period_end, item_filter),
        sort=sort,
        sort_direction=direction,
        toggle_sort_dir=make_toggle_sort_dir(sort, direction),
        wo_sort=wo_sort,
        wo_sort_direction=wo_direction,
        toggle_wo_sort_dir=make_toggle_sort_dir(wo_sort, wo_direction),
        list_query=list_query,
    )


@bp.get("/export.xlsx")
@login_required
@staff_required
def export_excel():
    period_start, period_end, item_filter = _consumption_filters()
    stock = load_inventory_stock()
    consumptions, total_cost = load_inventory_consumptions(
        period_start, period_end, item_filter, limit=5000
    )
    sheets = inventory_export_sheets(stock, consumptions, total_cost, period_start, period_end)
    return send_excel(
        f"inventory-{period_start.isoformat()}-{period_end.isoformat()}.xlsx",
        sheets,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@manager_required
def new():
    if request.method == "POST":
        _save(InventoryItem())
        return redirect(url_for("inventory.index"))
    return render_template("inventory/form.html", item=None, **_form_ctx())


@bp.route("/<int:iid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def edit(iid: int):
    it = db.session.get(InventoryItem, iid) or abort(404)
    if request.method == "POST":
        _save(it)
        return redirect(url_for("inventory.index"))
    return render_template("inventory/form.html", item=it, **_form_ctx(it))


@bp.post("/<int:iid>/delete")
@login_required
@manager_required
def delete(iid: int):
    it = db.session.get(InventoryItem, iid) or abort(404)
    db.session.delete(it)
    db.session.commit()
    return redirect(url_for("inventory.index"))


@bp.post("/<int:iid>/move")
@login_required
@manager_required
def move(iid: int):
    it = db.session.get(InventoryItem, iid) or abort(404)
    delta = float(request.form.get("delta") or 0)
    reason = request.form.get("reason", "")
    new_qty = (it.qty or 0) + delta
    if new_qty < -1e-9:
        flash(
            f"Нельзя списать больше остатка: есть {it.qty:g} {it.unit}",
            "error",
        )
        return redirect(url_for("inventory.index"))
    it.qty = round(new_qty, 4)
    db.session.add(InventoryMovement(item_id=it.id, delta=delta, reason=reason))
    detail = f"{it.name}: {delta:+.4g} {it.unit}, остаток {it.qty:g}"
    if reason:
        detail += f" — {reason}"
    log_audit("inventory.move", entity="inventory_item", entity_id=it.id, details=detail)
    db.session.commit()
    flash("Движение склада записано", "success")
    return redirect(url_for("inventory.index"))


def _form_ctx(item: InventoryItem | None = None) -> dict:
    unit = (item.unit if item else None) or DEFAULT_INVENTORY_UNIT
    if unit not in INVENTORY_UNITS:
        unit = DEFAULT_INVENTORY_UNIT
    return {
        "inventory_units": INVENTORY_UNITS,
        "selected_unit": unit,
    }


def _save(it: InventoryItem):
    f = request.form
    it.name = f.get("name", "").strip()
    it.sku = f.get("sku", "").strip()
    unit = f.get("unit", DEFAULT_INVENTORY_UNIT).strip()
    it.unit = unit if unit in INVENTORY_UNITS else DEFAULT_INVENTORY_UNIT
    it.qty = float(f.get("qty") or 0)
    it.min_qty = float(f.get("min_qty") or 0)
    it.cost_price = float(f.get("cost_price") or 0)
    if not it.id:
        db.session.add(it)
    db.session.commit()
    flash("Позиция сохранена", "success")
