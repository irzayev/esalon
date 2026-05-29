"""Lookup orders by public number (DDMM-XXX)."""
import re

from flask import abort

from ..models.order import Order

ORDER_NUMBER_RE = r"\d{4}-\d{3}"


def get_order_by_number(number: str) -> Order:
    if not re.fullmatch(ORDER_NUMBER_RE, number or ""):
        abort(404)
    order = Order.query.filter_by(number=number).first()
    if not order:
        abort(404)
    return order
