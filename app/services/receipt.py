"""Receipt template rendering for print."""
from __future__ import annotations

import re
from html import escape

from ..models.order import Order
from ..models.payment import PaymentMethod, PaymentStatus
from ..models.settings import Settings
from ..utils.i18n import translate

DEFAULT_RECEIPT_TEMPLATE = """<div class="space-y-4 text-sm leading-relaxed">
  {logo}
  <div class="text-center">
    <p class="text-lg font-semibold">{company_name}</p>
    <p class="text-slate-600 mt-1">{company_address}</p>
    <p class="text-slate-600">VÖEN: {company_tax_id}</p>
  </div>
  <div class="border-t border-b border-slate-200 py-3 text-center">
    <p class="mt-1">Заказ № {order_number}</p>
    <p class="text-slate-600">{order_date} · {order_time}</p>
    <p class="mt-2">Кассир: {cashier}</p>
  </div>
  <div>
    <p><span class="text-slate-500">Клиент:</span> {client_name}</p>
    <p><span class="text-slate-500">Телефон:</span> {client_phone}</p>
    <p><span class="text-slate-500">Авто:</span> {car_info}</p>
  </div>
  {items_table}
  <div class="space-y-1 border-t border-slate-200 pt-3">
    <div class="flex justify-between"><span>Подытог</span><span>{subtotal}</span></div>
    <div class="flex justify-between"><span>Скидка</span><span>{discount}</span></div>
    <div class="flex justify-between"><span>НДС</span><span>{vat}</span></div>
    <div class="flex justify-between font-semibold text-base"><span>Итого</span><span>{total}</span></div>
    <div class="flex justify-between text-emerald-700"><span>Оплачено</span><span>{paid}</span></div>
  </div>
  <div class="border-t border-slate-200 pt-3 space-y-1">
    <p class="font-medium">Оплата</p>
    <div class="flex justify-between"><span>Наличные</span><span>{payment_cash}</span></div>
    <div class="flex justify-between"><span>Карта</span><span>{payment_card}</span></div>
    <div class="flex justify-between"><span>Бонусы</span><span>{payment_bonus}</span></div>
  </div>
  {contacts_block}
  {footer_note}
</div>"""

RECEIPT_PLACEHOLDERS = [
    ("{company_name}", "Название компании"),
    ("{company_address}", "Адрес"),
    ("{company_tax_id}", "VÖEN"),
    ("{contacts}", "Контакты (текст)"),
    ("{instagram}", "Instagram / сайт"),
    ("{contacts_block}", "Контакты (HTML-блок)"),
    ("{logo}", "Логотип (HTML)"),
    ("{receipt_number}", "Номер чека"),
    ("{order_number}", "Номер заказа"),
    ("{order_date}", "Дата"),
    ("{order_time}", "Время"),
    ("{cashier}", "Кассир"),
    ("{client_name}", "Клиент"),
    ("{client_phone}", "Телефон клиента"),
    ("{car_info}", "Автомобиль"),
    ("{items_table}", "Таблица позиций (HTML)"),
    ("{subtotal}", "Подытог"),
    ("{discount}", "Скидка"),
    ("{vat}", "НДС"),
    ("{total}", "Итого"),
    ("{paid}", "Оплачено"),
    ("{currency}", "Валюта"),
    ("{payment_cash}", "Наличные и перевод"),
    ("{payment_card}", "Карта, POS, Azericard"),
    ("{payment_bonus}", "Бонусы"),
    ("{footer_note}", "Примечание внизу (HTML)"),
]


def _money(amount: float, currency: str) -> str:
    return f"{amount:.2f} {currency}"


def _payment_totals(order: Order) -> dict[str, float]:
    cash = card = bonus = 0.0
    for p in order.payments:
        if p.status != PaymentStatus.SUCCESS:
            continue
        if p.method in (PaymentMethod.CASH, PaymentMethod.TRANSFER):
            cash += p.amount
        elif p.method in (PaymentMethod.POS, PaymentMethod.AZERICARD):
            card += p.amount
        elif p.method == PaymentMethod.BONUS:
            bonus += p.amount
    return {"cash": cash, "card": card, "bonus": bonus}


def _strip_receipt_number_line(template: str) -> str:
    """Remove receipt-number row from built-in or saved templates."""
    return re.sub(
        r"\s*<p[^>]*>[\s\S]*?\{receipt_number\}[\s\S]*?</p>\s*",
        "",
        template,
        flags=re.IGNORECASE,
    )


def _build_items_table(order: Order, currency: str) -> str:
    if not order.items:
        return (
            f'<p class="text-center text-slate-500 py-4">'
            f"{escape(translate('receipt.no_items'))}</p>"
        )

    rows = []
    for it in order.items:
        rows.append(
            "<tr class=\"border-b border-slate-100\">"
            f"<td class=\"py-2 pr-2\">{escape(it.name)}</td>"
            f"<td class=\"py-2 text-center\">{it.qty:g}</td>"
            f"<td class=\"py-2 text-right\">{_money(it.price, currency)}</td>"
            f"<td class=\"py-2 text-right font-medium\">{_money(it.total, currency)}</td>"
            "</tr>"
        )
    body = "".join(rows)
    col_name = escape(translate("receipt.table.product"))
    col_qty = escape(translate("receipt.table.qty"))
    col_price = escape(translate("receipt.table.price"))
    col_total = escape(translate("receipt.table.total"))
    return (
        '<table class="w-full text-sm">'
        '<thead><tr class="text-left text-slate-500 border-b border-slate-200">'
        f'<th class="py-2">{col_name}</th><th class="py-2">{col_qty}</th>'
        f'<th class="py-2 text-right">{col_price}</th>'
        f'<th class="py-2 text-right">{col_total}</th>'
        "</tr></thead><tbody>"
        f"{body}</tbody></table>"
    )


def build_receipt_context(
    order: Order,
    settings: Settings | None = None,
    *,
    cashier: str = "",
    payment_totals: dict[str, float] | None = None,
    logo_url: str | None = None,
) -> dict[str, str]:
    s = settings or Settings.get()
    currency = s.default_currency or "AZN"
    totals = payment_totals or _payment_totals(order)
    receipt_number = f"{order.id:05d}"

    client_name = order.client.name if order.client else "—"
    client_phone = order.client.phone if order.client else "—"
    car_parts = []
    if order.car:
        if order.car.plate:
            car_parts.append(order.car.plate)
        brand_model = " ".join(p for p in [order.car.brand, order.car.model] if p)
        if brand_model:
            car_parts.append(brand_model)
    car_info = " · ".join(car_parts) if car_parts else "—"

    logo_html = ""
    url = logo_url or s.logo_url()
    if url:
        logo_html = (
            f'<div class="flex justify-center mb-2">'
            f'<img src="{escape(url)}" alt="" class="h-14 max-w-[180px] object-contain"/>'
            f"</div>"
        )

    contacts = s.contact_block()
    contacts_block = ""
    if contacts:
        contacts_block = (
            '<div class="text-center text-xs text-slate-600 border-t border-slate-200 pt-4 '
            'whitespace-pre-line">'
            f"{escape(contacts)}"
            "</div>"
        )

    footer_note = ""
    if s.receipt_footer_note:
        footer_note = (
            f'<p class="text-center text-xs text-slate-500 mt-4 border-t border-slate-200 pt-4">'
            f"{escape(s.receipt_footer_note)}"
            "</p>"
        )

    # Plain-text values are escaped to prevent stored XSS via client/company
    # data. Pre-built HTML blocks (built above with their own escaping) are
    # kept raw and listed in _RAW_HTML_KEYS so they are not double-escaped.
    text_ctx = {
        "company_name": s.company_name or "—",
        "company_address": s.company_address or "—",
        "company_phone": s.company_phone or "",
        "company_email": s.company_email or "",
        "company_website": s.company_website or "",
        "company_tax_id": s.company_tax_id or "—",
        "contacts": contacts,
        "instagram": s.company_website or "",
        "receipt_number": receipt_number,
        "order_number": order.number or str(order.id),
        "order_id": str(order.id),
        "order_date": order.created_at.strftime("%d.%m.%Y"),
        "order_time": order.created_at.strftime("%H:%M"),
        "order_datetime": order.created_at.strftime("%d.%m.%Y %H:%M"),
        "cashier": cashier or s.receipt_cashier_name or "—",
        "client_name": client_name,
        "client_phone": client_phone,
        "car_info": car_info,
        "subtotal": _money(order.subtotal or 0, currency),
        "discount": _money(order.discount_value or 0, currency),
        "vat": _money(order.vat_amount or 0, currency),
        "total": _money(order.final_total or 0, currency),
        "paid": _money(order.paid_total, currency),
        "currency": currency,
        "payment_cash": _money(totals["cash"], currency),
        "payment_card": _money(totals["card"], currency),
        "payment_bonus": _money(totals["bonus"], currency),
    }
    ctx = {key: escape(value) for key, value in text_ctx.items()}
    ctx.update({
        "contacts_block": contacts_block,
        "logo": logo_html,
        "items_table": _build_items_table(order, currency),
        "footer_note": footer_note,
    })
    return ctx


def render_receipt_html(
    order: Order,
    settings: Settings | None = None,
    *,
    cashier: str = "",
    payment_totals: dict[str, float] | None = None,
    logo_url: str | None = None,
) -> str:
    s = settings or Settings.get()
    tpl = _strip_receipt_number_line(
        (s.receipt_template or "").strip() or DEFAULT_RECEIPT_TEMPLATE
    )
    ctx = build_receipt_context(
        order, s, cashier=cashier, payment_totals=payment_totals, logo_url=logo_url
    )
    result = tpl
    for key, value in ctx.items():
        result = result.replace("{" + key + "}", value)
    return result

