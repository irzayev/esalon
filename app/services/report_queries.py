"""Shared queries for finance, inventory, and consolidated reports."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models.cash_expense import CashExpense
from ..models.inventory import InventoryItem, InventoryMovement
from ..models.order import Order
from ..models.payment import Payment, PaymentMethod, PaymentStatus
from ..utils.branches import filter_cash_expenses, filter_orders, filter_payments
from .order_assignees import orders_with_assignees_query
from .order_discount import format_order_discount_display
from .order_work_time import batch_order_work_minutes
from .payroll import payroll_rows_for_period
from .table_export import format_money


METHOD_LABELS_SHORT = {
    PaymentMethod.CASH: "Наличные",
    PaymentMethod.POS: "POS",
    PaymentMethod.AZERICARD: "Azericard",
    PaymentMethod.TRANSFER: "Перевод",
    PaymentMethod.BONUS: "Бонусы",
    PaymentMethod.MIXED: "Смешанная",
}


def parse_date_range(from_raw: str | None, to_raw: str | None) -> tuple[date, date]:
    today = date.today()
    start_default = today.replace(day=1)
    end_default = today
    try:
        period_start = datetime.strptime(from_raw, "%Y-%m-%d").date() if from_raw else start_default
    except ValueError:
        period_start = start_default
    try:
        period_end = datetime.strptime(to_raw, "%Y-%m-%d").date() if to_raw else end_default
    except ValueError:
        period_end = end_default
    if period_end < period_start:
        period_end = period_start
    return period_start, period_end


def sum_cash_expenses(period_start: date, period_end: date, branch_id: int | None) -> float:
    q = (
        db.session.query(func.coalesce(func.sum(CashExpense.amount), 0))
        .filter(CashExpense.expense_date >= period_start)
        .filter(CashExpense.expense_date <= period_end)
    )
    return round(float(filter_cash_expenses(q, branch_id).scalar() or 0), 2)


def load_cash_expenses(day: date, branch_id: int | None) -> tuple[list[CashExpense], float]:
    q = CashExpense.query.filter(CashExpense.expense_date == day)
    expenses = filter_cash_expenses(q, branch_id).order_by(CashExpense.created_at.desc()).all()
    total = round(sum(float(e.amount or 0) for e in expenses), 2)
    return expenses, total


def load_period_cash_expenses(
    period_start: date,
    period_end: date,
    branch_id: int | None,
    *,
    limit: int = 5000,
) -> list[CashExpense]:
    q = (
        CashExpense.query.filter(CashExpense.expense_date >= period_start)
        .filter(CashExpense.expense_date <= period_end)
    )
    return (
        filter_cash_expenses(q, branch_id)
        .options(joinedload(CashExpense.branch))
        .order_by(CashExpense.expense_date.desc(), CashExpense.created_at.desc())
        .limit(limit)
        .all()
    )


def compute_period_pnl(period_start: date, period_end: date, branch_id: int | None) -> dict:
    """Net income: revenue − payroll − items − manual cash expenses."""
    revenue_total = load_revenue_period(period_start, period_end, branch_id)["total"]
    payroll_rows = payroll_rows_for_period(period_start, period_end, branch_id)
    payroll_total = round(sum(r["total"] for r in payroll_rows), 2)
    _, inventory_cost = load_inventory_consumptions(period_start, period_end)
    cash_expenses_total = sum_cash_expenses(period_start, period_end, branch_id)
    net_income = round(revenue_total - payroll_total - inventory_cost - cash_expenses_total, 2)
    return {
        "revenue_total": revenue_total,
        "payroll_total": payroll_total,
        "inventory_cost": inventory_cost,
        "cash_expenses_total": cash_expenses_total,
        "net_income": net_income,
    }


def load_cash_day(day: date, branch_id: int | None) -> dict:
    rows_q = (
        db.session.query(Payment.method, func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.status == PaymentStatus.SUCCESS)
        .filter(func.date(Payment.created_at) == day)
    )
    rows = filter_payments(rows_q, branch_id).group_by(Payment.method).all()
    by_method = {m.value: 0.0 for m in PaymentMethod}
    for m, amt in rows:
        by_method[m] = float(amt or 0)
    total = sum(by_method.values())

    pay_q = Payment.query.filter(func.date(Payment.created_at) == day)
    payments = filter_payments(pay_q, branch_id).order_by(Payment.created_at.desc()).all()
    expenses, expenses_total = load_cash_expenses(day, branch_id)
    return {
        "day": day,
        "by_method": by_method,
        "total": total,
        "payments": payments,
        "expenses": expenses,
        "expenses_total": expenses_total,
        "net_total": round(total - expenses_total, 2),
    }


def load_revenue_period(period_start: date, period_end: date, branch_id: int | None) -> dict:
    rows_q = (
        db.session.query(Payment.method, func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.status == PaymentStatus.SUCCESS)
        .filter(func.date(Payment.created_at) >= period_start)
        .filter(func.date(Payment.created_at) <= period_end)
    )
    rows = filter_payments(rows_q, branch_id).group_by(Payment.method).all()
    by_method = {m.value: 0.0 for m in PaymentMethod}
    for m, amt in rows:
        by_method[m] = float(amt or 0)
    total = sum(by_method.values())

    pay_q = (
        Payment.query.filter(Payment.status == PaymentStatus.SUCCESS)
        .filter(func.date(Payment.created_at) >= period_start)
        .filter(func.date(Payment.created_at) <= period_end)
    )
    payments = filter_payments(pay_q, branch_id).order_by(Payment.created_at.desc()).limit(2000).all()
    return {"by_method": by_method, "total": total, "payments": payments}


def load_inventory_stock(
    *,
    sort: str = "name",
    direction: str = "asc",
) -> list[InventoryItem]:
    from ..utils.list_sort import sql_order

    sort_map = {
        "name": InventoryItem.name,
        "sku": InventoryItem.sku,
        "qty": InventoryItem.qty,
        "min": InventoryItem.min_qty,
        "cost": InventoryItem.cost_price,
    }
    col = sort_map.get(sort, InventoryItem.name)
    nullable = sort == "sku"
    return (
        InventoryItem.query.order_by(
            sql_order(col, direction, nullable=nullable),
            InventoryItem.name.asc(),
        ).all()
    )


def load_inventory_consumptions(
    period_start: date,
    period_end: date,
    item_filter: int | None = None,
    *,
    limit: int = 5000,
    sort: str = "date",
    direction: str = "desc",
) -> tuple[list[dict], float]:
    from ..models.order import Order
    from ..utils.list_sort import sql_order

    _SORT_KEYS = frozenset({"date", "order", "item", "qty", "cost"})
    if sort not in _SORT_KEYS:
        sort = "date"
    if direction not in ("asc", "desc"):
        direction = "desc"

    q = (
        InventoryMovement.query.filter(InventoryMovement.delta < 0)
        .filter(func.date(InventoryMovement.created_at) >= period_start)
        .filter(func.date(InventoryMovement.created_at) <= period_end)
        .join(InventoryItem, InventoryMovement.item_id == InventoryItem.id)
        .outerjoin(Order, InventoryMovement.order_id == Order.id)
    )
    if item_filter:
        q = q.filter(InventoryMovement.item_id == item_filter)

    line_cost_expr = func.abs(InventoryMovement.delta) * func.coalesce(
        InventoryItem.cost_price, 0
    )
    sort_map = {
        "date": InventoryMovement.created_at,
        "order": Order.number,
        "item": InventoryItem.name,
        "qty": func.abs(InventoryMovement.delta),
        "cost": line_cost_expr,
    }
    sort_col = sort_map[sort]
    order_clause = sql_order(
        sort_col, direction, nullable=sort in {"order", "item"}
    )

    consumptions = (
        q.options(
            joinedload(InventoryMovement.item),
            joinedload(InventoryMovement.order),
        )
        .order_by(order_clause, InventoryMovement.created_at.desc())
        .limit(limit)
        .all()
    )

    rows = []
    total_cost = 0.0
    for m in consumptions:
        qty = abs(float(m.delta))
        unit_cost = float(m.item.cost_price or 0) if m.item else 0.0
        line_cost = round(qty * unit_cost, 2)
        total_cost += line_cost
        rows.append({"movement": m, "qty": qty, "line_cost": line_cost, "order": m.order})
    return rows, round(total_cost, 2)


def load_period_orders(
    period_start: date,
    period_end: date,
    branch_id: int | None,
    *,
    limit: int = 5000,
) -> list[Order]:
    q = (
        Order.query.filter(func.date(Order.created_at) >= period_start)
        .filter(func.date(Order.created_at) <= period_end)
    )
    return (
        orders_with_assignees_query(filter_orders(q, branch_id))
        .options(
            joinedload(Order.client),
            joinedload(Order.promo_code),
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
        .all()
    )


def load_period_report(period_start: date, period_end: date, branch_id: int | None) -> dict:
    revenue = load_revenue_period(period_start, period_end, branch_id)
    payroll_rows = payroll_rows_for_period(period_start, period_end, branch_id)
    consumptions, inventory_cost = load_inventory_consumptions(period_start, period_end)
    stock = load_inventory_stock()

    payroll_totals = {
        "base": round(sum(r["base"] for r in payroll_rows), 2),
        "bonus": round(sum(r["bonus"] for r in payroll_rows), 2),
        "total": round(sum(r["total"] for r in payroll_rows), 2),
    }
    revenue_total = revenue["total"]
    cash_expenses = load_period_cash_expenses(period_start, period_end, branch_id)
    cash_expenses_total = sum_cash_expenses(period_start, period_end, branch_id)
    orders = load_period_orders(period_start, period_end, branch_id)
    orders_total = round(sum(float(o.final_total or 0) for o in orders), 2)
    orders_work_minutes = batch_order_work_minutes(orders)
    margin = round(
        revenue_total - payroll_totals["total"] - inventory_cost - cash_expenses_total,
        2,
    )

    return {
        "period_start": period_start,
        "period_end": period_end,
        "branch_id": branch_id,
        "revenue": revenue,
        "payroll_rows": payroll_rows,
        "payroll_totals": payroll_totals,
        "consumptions": consumptions,
        "inventory_cost": inventory_cost,
        "cash_expenses": cash_expenses,
        "cash_expenses_total": cash_expenses_total,
        "stock": stock,
        "revenue_total": revenue_total,
        "margin": margin,
        "orders": orders,
        "orders_total": orders_total,
        "orders_work_minutes": orders_work_minutes,
    }


def cash_export_sections(data: dict) -> list[dict]:
    by_method = data["by_method"]

    payment_rows = []
    for p in data["payments"]:
        order_num = p.order.number if p.order else "—"
        payment_rows.append([
            p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "",
            f"#{order_num}",
            p.method_label,
            p.status,
            format_money(p.amount),
        ])

    expense_rows = [
        [e.name, format_money(e.amount)]
        for e in data.get("expenses", [])
    ]
    sections = [
        {
            "title": "Итоги по методам оплаты",
            "headers": ["Метод", "Сумма"],
            "rows": [[METHOD_LABELS_SHORT.get(m, m.value), format_money(by_method.get(m.value, 0))] for m in PaymentMethod],
            "summary_rows": [["Итого", format_money(data["total"])]],
            "numeric_last": True,
        },
        {
            "title": "Платежи",
            "headers": ["Время", "Заказ", "Метод", "Статус", "Сумма"],
            "rows": payment_rows,
            "numeric_last": True,
        },
    ]
    if expense_rows or data.get("expenses_total"):
        sections.append({
            "title": "Расходы",
            "headers": ["Наименование", "Сумма"],
            "rows": expense_rows,
            "summary_rows": [["Итого расходов", format_money(data.get("expenses_total", 0))]],
            "numeric_last": True,
        })
        sections.append({
            "title": "Итог дня",
            "headers": ["Показатель", "Сумма"],
            "rows": [
                ["Выручка", format_money(data["total"])],
                ["Расходы", format_money(data.get("expenses_total", 0))],
                ["Чистый итог", format_money(data.get("net_total", data["total"]))],
            ],
            "numeric_last": True,
        })
    return sections


def inventory_export_sheets(
    stock: list[InventoryItem],
    consumptions: list[dict],
    total_cost: float,
    period_start: date,
    period_end: date,
) -> list[dict]:
    stock_rows = [
        [
            it.name,
            it.sku or "",
            f"{it.qty:g} {it.unit}",
            f"{it.min_qty:g}",
            format_money(it.cost_price),
            it.purchased_at.strftime("%d.%m.%Y") if it.purchased_at else "",
            it.expires_at.strftime("%d.%m.%Y") if it.expires_at else "",
            it.notes or "",
            "Да" if it.is_low else "",
            "Да" if it.is_expired else "",
        ]
        for it in stock
    ]
    cons_rows = []
    for row in consumptions:
        m = row["movement"]
        order_num = f"#{row['order'].number}" if row.get("order") else "—"
        cons_rows.append([
            m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
            order_num,
            m.item.name if m.item else "—",
            f"{row['qty']:g} {m.item.unit if m.item else ''}",
            format_money(row["line_cost"]),
            m.reason or "",
        ])

    return [
        {
            "name": "Остатки",
            "headers": ["Название", "SKU", "Кол-во", "Мин.", "Себестоимость", "Дата покупки", "Срок годности", "Заметки", "Мало", "Просрочен"],
            "rows": stock_rows,
        },
        {
            "name": "Списания",
            "headers": ["Дата", "Заказ", "Товар", "Кол-во", "Себестоимость", "Причина"],
            "rows": cons_rows,
            "summary_rows": [["", "", "", "Итого за период", format_money(total_cost), ""]],
        },
    ]


def reports_export_sections(report: dict) -> list[dict]:
    ps, pe = report["period_start"], report["period_end"]
    period_label = f"{ps.strftime('%d.%m.%Y')} — {pe.strftime('%d.%m.%Y')}"
    revenue = report["revenue"]
    payroll_totals = report["payroll_totals"]

    summary_section = {
        "title": "Сводка",
        "headers": ["Показатель", "Значение"],
        "rows": [
            ["Период", period_label],
            ["Выручка (успешные оплаты)", format_money(report["revenue_total"])],
            ["Зарплаты (расчёт)", format_money(payroll_totals["total"])],
            ["Расход товаров", format_money(report["inventory_cost"])],
            ["Прочие расходы (касса)", format_money(report.get("cash_expenses_total", 0))],
            ["Чистый доход", format_money(report["margin"])],
        ],
    }

    revenue_rows = [
        [METHOD_LABELS_SHORT.get(m, m.value), format_money(revenue["by_method"].get(m.value, 0))]
        for m in PaymentMethod
    ]
    revenue_section = {
        "title": "Выручка по методам оплаты",
        "headers": ["Метод", "Сумма"],
        "rows": revenue_rows,
        "summary_rows": [["Итого", format_money(revenue["total"])]],
        "numeric_last": True,
    }

    payroll_section = {
        "title": "Зарплаты",
        "headers": ["Сотрудник", "Должность", "Модель", "KPI", "Машин", "Выручка", "База", "Бонус", "Итого"],
        "rows": [
            [
                r["employee"].name,
                r["employee"].position or "",
                r["employee"].salary_model,
                f"{r['kpi_score']}%",
                r["visits_count"],
                format_money(r["revenue_total"]),
                format_money(r["base"]),
                format_money(r["bonus"]),
                format_money(r["total"]),
            ]
            for r in report["payroll_rows"]
        ],
        "summary_rows": [
            [
                "Итого",
                "",
                "",
                "",
                "",
                "",
                format_money(payroll_totals["base"]),
                format_money(payroll_totals["bonus"]),
                format_money(payroll_totals["total"]),
            ]
        ],
        "numeric_last": True,
    }

    cons_rows = []
    for row in report["consumptions"][:500]:
        m = row["movement"]
        order_num = f"#{row['order'].number}" if row.get("order") else "—"
        cons_rows.append([
            m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
            order_num,
            m.item.name if m.item else "—",
            f"{row['qty']:g}",
            format_money(row["line_cost"]),
        ])
    inventory_section = {
        "title": "Расход товаров (списания)",
        "headers": ["Дата", "Заказ", "Товар", "Кол-во", "Себестоимость"],
        "rows": cons_rows,
        "summary_rows": [["", "", "Итого", "", format_money(report["inventory_cost"])]],
        "numeric_last": True,
    }

    show_branch = report.get("branch_id") is None
    expense_headers = ["Дата", "Наименование", "Сумма"]
    if show_branch:
        expense_headers = ["Дата", "Филиал", "Наименование", "Сумма"]
    expense_rows = []
    for e in report.get("cash_expenses", [])[:500]:
        row = [
            e.expense_date.strftime("%d.%m.%Y") if e.expense_date else "",
            e.name,
            format_money(e.amount),
        ]
        if show_branch:
            row.insert(1, e.branch.name if e.branch else "—")
        expense_rows.append(row)

    cash_expenses_section = {
        "title": "Расходы кассы",
        "headers": expense_headers,
        "rows": expense_rows,
        "summary_rows": [
            (["Итого", "", "", format_money(report.get("cash_expenses_total", 0))]
             if show_branch
             else ["Итого", format_money(report.get("cash_expenses_total", 0))])
        ],
        "numeric_last": True,
    }

    work_map = report.get("orders_work_minutes") or {}
    order_rows = []
    for o in report.get("orders", [])[:500]:
        lbl, _ = o.status_label
        wm = work_map.get(o.id)
        work_cell = "—" if wm is None else f"{int(wm)} мин"
        order_rows.append([
            o.number or "",
            lbl,
            work_cell,
            o.assignee_names,
            o.client.name if o.client else "—",
            o.client.phone if o.client else "—",
            (o.updated_at or o.created_at).strftime("%d.%m.%Y %H:%M")
            if (o.updated_at or o.created_at)
            else "",
            o.created_at.strftime("%d.%m.%Y %H:%M") if o.created_at else "",
            format_money(o.final_total),
            format_order_discount_display(o),
        ])
    orders_section = {
        "title": "Заказы",
        "headers": [
            "№",
            "Статус",
            "В работе",
            "Исполнители",
            "Клиент",
            "Телефон",
            "Обновлён",
            "Создан",
            "Сумма",
            "Скидка",
        ],
        "rows": order_rows,
        "summary_rows": [
            ["", "", "", "", "", "", "Итого", format_money(report.get("orders_total", 0)), ""]
        ],
        "numeric_last": True,
    }

    return [
        summary_section,
        orders_section,
        revenue_section,
        payroll_section,
        cash_expenses_section,
        inventory_section,
    ]
