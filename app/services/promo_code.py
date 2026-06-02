"""Promo code validation, generation, and order usage tracking."""
from __future__ import annotations

import random
import string
from datetime import datetime, time

from ..extensions import db
from ..models.order import Order, calc_order_discount
from ..models.promo_code import PromoCode
from ..services.scheduling import local_to_utc_naive, utc_naive_to_local

_PROMO_CHARS = string.ascii_uppercase + string.digits


def normalize_promo_code(raw: str) -> str:
    return (raw or "").strip().upper()


def parse_promo_datetime_local(raw: str | None) -> datetime | None:
    """Parse datetime-local value (app timezone) to UTC naive."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        local = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return local_to_utc_naive(local)


def format_promo_datetime_local(dt_utc: datetime | None) -> str:
    """Format UTC naive datetime for datetime-local input."""
    if not dt_utc:
        return ""
    if isinstance(dt_utc, datetime):
        value = dt_utc
    else:
        from datetime import date

        if isinstance(dt_utc, date):
            value = datetime.combine(dt_utc, time.min)
        else:
            return ""
    local = utc_naive_to_local(value)
    return local.strftime("%Y-%m-%dT%H:%M") if local else ""


def generate_promo_code(length: int = 6) -> str:
    length = max(4, min(8, int(length or 6)))
    for _ in range(100):
        code = "".join(random.choices(_PROMO_CHARS, k=length))
        if not PromoCode.query.filter_by(code=code).first():
            return code
    raise ValueError("promo.error.generate_failed")


def validate_promo_code(raw: str) -> tuple[PromoCode | None, str | None]:
    """Return (promo, i18n_error_key). Error key is None on success."""
    code = normalize_promo_code(raw)
    if not code:
        return None, "promo.error.empty"
    if len(code) < 4 or len(code) > 8:
        return None, "promo.error.length"
    if not code.isalnum():
        return None, "promo.error.chars"

    promo = PromoCode.query.filter_by(code=code).first()
    if not promo:
        return None, "promo.error.not_found"
    if not promo.is_active:
        return None, "promo.error.inactive"
    if promo.is_not_yet_active():
        return None, "promo.error.not_started"
    if promo.is_expired():
        return None, "promo.error.expired"
    if not promo.is_unlimited and (promo.used_count or 0) >= promo.max_uses:
        return None, "promo.error.limit"
    if not promo.discount_value or promo.discount_value <= 0:
        return None, "promo.error.invalid_config"
    return promo, None


def calc_promo_discount(subtotal: float, promo: PromoCode | None) -> float:
    if not promo:
        return 0.0
    amount = calc_order_discount(subtotal, promo.discount_type, promo.discount_value)
    return min(max(amount, 0.0), max(subtotal, 0.0))


def record_promo_use_if_order_paid(order_id: int) -> None:
    order = db.session.get(Order, order_id)
    if not order or not order.is_paid or not order.promo_code_id:
        return
    if order.promo_use_counted:
        return

    promo = db.session.get(PromoCode, order.promo_code_id)
    if not promo:
        return

    promo.used_count = (promo.used_count or 0) + 1
    order.promo_use_counted = True
    db.session.commit()
