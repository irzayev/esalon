"""Generate printable invoice/receipt PDF from custom HTML template."""
from __future__ import annotations

from ..models.order import Order
from ..models.settings import Settings
from .pdf_fonts import html_to_pdf_bytes
from .receipt import render_receipt_document, _payment_totals


def build_order_invoice_pdf(
    order: Order,
    *,
    cashier: str = "",
    base_url: str = "http://127.0.0.1:7000",
) -> bytes:
    """Return PDF bytes for a single order."""
    settings = Settings.get()
    html = render_receipt_document(
        order,
        settings,
        cashier=cashier,
        payment_totals=_payment_totals(order),
        base_url=base_url,
    )
    return html_to_pdf_bytes(html)
