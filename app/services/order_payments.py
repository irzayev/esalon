"""Shared helpers after order payment (cashback, etc.)."""
from __future__ import annotations

from ..extensions import db
from ..models.bonus import BonusTransaction, BonusType, BonusWallet
from ..models.order import Order, OrderStatus
from ..models.payment import PaymentMethod, PaymentStatus
from ..models.settings import Settings

CASHBACK_ELIGIBLE_STATUSES = (OrderStatus.DONE,)


def apply_cashback_if_order_paid(order_id: int) -> None:
    order = db.session.get(Order, order_id)
    if not order or not order.is_paid:
        return
    if order.status not in CASHBACK_ELIGIBLE_STATUSES:
        return
    s = Settings.get()
    if not s.bonus_enabled:
        return
    if not order.client_id:
        return
    # Skip if cashback already applied for this order
    existing = BonusTransaction.query.filter_by(
        source_order_id=order.id, type=BonusType.EARN, comment="cashback"
    ).first()
    if existing:
        return
    cashback = round((order.final_total or 0) * s.bonus_cashback_percent / 100, 2)
    if cashback <= 0:
        return
    wallet = order.client.wallet
    if not wallet:
        wallet = BonusWallet(client_id=order.client_id)
        db.session.add(wallet)
    wallet.balance += cashback
    wallet.lifetime_earned += cashback
    db.session.add(
        BonusTransaction(
            client_id=order.client_id,
            type=BonusType.EARN,
            amount=cashback,
            source_order_id=order.id,
            comment="cashback",
        )
    )
    db.session.commit()


def apply_post_payment_hooks(order_id: int) -> None:
    apply_cashback_if_order_paid(order_id)
    from .promo_code import record_promo_use_if_order_paid

    record_promo_use_if_order_paid(order_id)


def apply_order_completion_hooks(order_id: int) -> None:
    """Cashback and other hooks when order is ready or delivered."""
    apply_cashback_if_order_paid(order_id)
