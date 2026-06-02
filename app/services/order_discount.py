"""Order discount display helpers."""
from __future__ import annotations

from ..models.order import Order
from .table_export import format_money


def _format_percent(value: float) -> str:
    if value == int(value):
        return f"{int(value)}%"
    return f"{value:g}%"


def format_order_discount_display(order: Order) -> str:
    """Human-readable summary of discounts applied to an order."""
    parts: list[str] = []

    discount_amount = order.discount_amount or 0
    if discount_amount > 0:
        if order.discount_type in ("percent", "manual") and order.discount_value:
            label = f"{_format_percent(float(order.discount_value))} (−{format_money(discount_amount)})"
        else:
            label = f"−{format_money(discount_amount)}"
        reason = (order.discount_reason or "").strip()
        if reason and reason != "—":
            label = f"{label} · {reason}"
        parts.append(label)

    promo_amount = order.promo_discount_amount or 0
    if promo_amount > 0 and (order.promo_code_text or order.promo_code_id):
        code = order.promo_code_text or "—"
        ptype = order.promo_discount_type_effective
        pval = order.promo_discount_value_effective
        if ptype == "percent" and pval:
            label = f"{code} {_format_percent(pval)} (−{format_money(promo_amount)})"
        elif ptype == "fixed" and pval:
            label = f"{code} −{format_money(promo_amount)}"
        else:
            label = f"{code} −{format_money(promo_amount)}"
        parts.append(label)

    return "; ".join(parts) if parts else "—"
