"""Branding helpers: contacts and WhatsApp message templates."""
from __future__ import annotations

from ..models.settings import Settings

DEFAULT_WA_READY = (
    "{company}\n"
    "Ваш автомобиль готов! Заказ #{order_number}.\n\n"
    "{contacts}"
)
DEFAULT_WA_BOOKING = (
    "{company}\n"
    "Вы записаны. Номер заказа: #{order_number}.\n\n"
    "{contacts}"
)
DEFAULT_WA_REMINDER = (
    "{company}\n"
    "Давно не были у нас — пора на мойку! Запишитесь удобное время.\n\n"
    "{contacts}"
)
DEFAULT_WA_PAYMENT = (
    "{company}\n"
    "Ödəniş üçün link / Ссылка для оплаты заказа #{order_number}\n"
    "Məbləğ / Сумма: {amount}\n"
    "{payment_link}\n\n"
    "{contacts}"
)
DEFAULT_WA_STATUS_CHANGE = (
    "{company}\n"
    "Статус заказа #{order_number}: {order_status}.\n\n"
    "{contacts}"
)


def client_order_track_url(order_number: str = "") -> str:
    """Public client portal URL with order number pre-filled (phone required on open)."""
    from flask import url_for

    number = (order_number or "").strip()
    if not number:
        return ""
    return url_for("client_portal.index", number=number, _external=True)


def build_wa_context(settings: Settings | None = None, **extra: str) -> dict[str, str]:
    s = settings or Settings.get()
    ctx = {
        "company": s.company_name or "Washer CRM",
        "phone": s.company_phone or "",
        "email": s.company_email or "",
        "address": s.company_address or "",
        "website": s.company_website or "",
        "instagram": s.company_website or "",
        "waze": s.company_waze or "",
        "contacts": s.contact_block(),
        "client_name": "",
        "order_number": "",
        "order_link": "",
        "amount": "",
        "payment_link": "",
        "order_status": "",
    }
    ctx.update({k: str(v) for k, v in extra.items()})
    if ctx.get("order_number") and not ctx.get("order_link"):
        ctx["order_link"] = client_order_track_url(ctx["order_number"])
    return ctx


def format_whatsapp_message(
    template: str,
    settings: Settings | None = None,
    *,
    default: str = DEFAULT_WA_READY,
    **extra: str,
) -> str:
    s = settings or Settings.get()
    tpl = (template or "").strip() or default
    ctx = build_wa_context(s, **extra)
    try:
        return tpl.format(**ctx).strip()
    except (KeyError, ValueError):
        return tpl
