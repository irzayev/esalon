"""Promo code validation, generation, and order usage tracking."""
from __future__ import annotations

import random
import string

from ..extensions import db
from ..models.order import Order, calc_order_discount
from ..models.promo_code import PromoCode

_PROMO_CHARS = string.ascii_uppercase + string.digits


def normalize_promo_code(raw: str) -> str:
    return (raw or "").strip().upper()


def generate_promo_code(length: int = 6) -> str:
    length = max(4, min(8, int(length or 6)))
    for _ in range(100):
        code = "".join(random.choices(_PROMO_CHARS, k=length))
        if not PromoCode.query.filter_by(code=code).first():
            return code
    raise ValueError("Не удалось сгенерировать уникальный промокод")


def validate_promo_code(raw: str) -> tuple[PromoCode | None, str]:
    code = normalize_promo_code(raw)
    if not code:
        return None, "Введите промокод"
    if len(code) < 4 or len(code) > 8:
        return None, "Промокод должен содержать от 4 до 8 символов"
    if not code.isalnum():
        return None, "Промокод может содержать только буквы и цифры"

    promo = PromoCode.query.filter_by(code=code).first()
    if not promo:
        return None, "Промокод не найден"
    if not promo.is_active:
        return None, "Промокод деактивирован"
    if promo.is_expired():
        return None, "Срок действия промокода истёк"
    if not promo.is_unlimited and (promo.used_count or 0) >= promo.max_uses:
        return None, "Лимит использований промокода исчерпан"
    if not promo.discount_value or promo.discount_value <= 0:
        return None, "Промокод настроен некорректно"
    return promo, ""


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
