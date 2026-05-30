"""Online payment link for the public client order tracking page."""
from __future__ import annotations

from flask import url_for

from ..extensions import db
from ..models.azericard import AzericardIntentStatus
from ..models.order import Order, OrderStatus
from ..models.payment import Payment, PaymentMethod, PaymentStatus
from ..models.settings import Settings
from .azericard import AzericardService


def client_portal_pay_enabled(settings: Settings | None = None) -> bool:
    s = settings or Settings.get()
    if not s.azericard_enabled or not s.azericard_client_portal_enabled:
        return False
    return AzericardService(s).enabled


def client_portal_pay_available(order: Order) -> bool:
    """Whether the client may start an online payment (button only — no Payment row yet)."""
    if order.status == OrderStatus.CANCELED:
        return False
    if order.is_paid or order.amount_due <= 0.01:
        return False
    return client_portal_pay_enabled()


def client_visible_payments(order: Order) -> list[Payment]:
    """Payments listed on the tracking page (hide unopened client-portal Azericard drafts)."""
    visible: list[Payment] = []
    for p in order.payments:
        intent = p.azericard_intent
        if (
            p.method == PaymentMethod.AZERICARD
            and p.status == PaymentStatus.PENDING
            and intent
            and intent.status == AzericardIntentStatus.CREATED
            and (intent.audit_channel or "") == "client_portal"
        ):
            continue
        visible.append(p)
    return visible


def get_or_create_client_pay_url(order: Order) -> str | None:
    """Return external Azericard checkout URL, reusing or creating a pending payment."""
    if order.status == OrderStatus.CANCELED:
        return None
    if order.is_paid or order.amount_due <= 0.01:
        return None
    if not client_portal_pay_enabled():
        return None

    amount_due = round(order.amount_due, 2)
    for p in sorted(order.payments, key=lambda row: row.created_at or 0, reverse=True):
        if (
            p.method == PaymentMethod.AZERICARD
            and p.status == PaymentStatus.PENDING
            and abs((p.amount or 0) - amount_due) < 0.01
            and p.azericard_intent
            and p.azericard_intent.pay_token
        ):
            return url_for(
                "payments.pay_checkout",
                token=p.azericard_intent.pay_token,
                _external=True,
            )

    az = AzericardService()
    payment = Payment(
        order_id=order.id,
        method=PaymentMethod.AZERICARD,
        amount=amount_due,
        status=PaymentStatus.PENDING,
    )
    db.session.add(payment)
    db.session.flush()
    intent = az.create_payment_link(
        payment=payment,
        business_order_id=order.id,
        amount=amount_due,
        audit_channel="client_portal",
    )
    db.session.commit()
    return url_for("payments.pay_checkout", token=intent.pay_token, _external=True)
