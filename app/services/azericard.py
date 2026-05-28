"""Azericard 3DSecure MPI integration.

Реализует подготовку payload для редиректа на платёжный шлюз
Azericard (форма POST на gateway_url) и базовую валидацию ответа.

Реальные ключи/секреты берутся из админских настроек (Settings).
"""
from __future__ import annotations
import hashlib
import hmac
from datetime import datetime
from dataclasses import dataclass

from ..models.settings import Settings


@dataclass
class AzericardPayment:
    order_id: int
    amount: float
    description: str
    back_ref_url: str  # куда вернуть клиента после оплаты


class AzericardService:
    """Подготовка платежей через Azericard."""

    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings.get()

    @property
    def enabled(self) -> bool:
        return bool(self.s.azericard_enabled and self.s.azericard_merchant_id)

    def build_form_payload(self, payment: AzericardPayment) -> dict:
        """Сформировать поля формы для POST на шлюз Azericard.

        Поля соответствуют документации Azericard 3DSecure MPI.
        """
        amount = f"{payment.amount:.2f}"
        order = f"{payment.order_id:06d}"
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        nonce = hashlib.sha1(f"{order}{timestamp}".encode()).hexdigest()[:16].upper()

        payload = {
            "AMOUNT": amount,
            "CURRENCY": self.s.azericard_currency or "944",
            "ORDER": order,
            "DESC": payment.description[:50],
            "MERCH_NAME": self.s.azericard_merchant_name or "",
            "MERCH_URL": self.s.azericard_merchant_url or "",
            "TERMINAL": self.s.azericard_terminal_id or "",
            "MERCH_GMT": "+4",
            "TRTYPE": "1",  # 1 = Sale
            "COUNTRY": self.s.azericard_country or "AZ",
            "TIMESTAMP": timestamp,
            "NONCE": nonce,
            "BACKREF": payment.back_ref_url,
            "LANG": "RU",
        }

        # MAC (P_SIGN) — конкатенация полей с длиной по спецификации Azericard
        mac_fields = [
            payload["AMOUNT"], payload["CURRENCY"], payload["TERMINAL"],
            payload["TRTYPE"], payload["ORDER"], payload["TIMESTAMP"], payload["NONCE"],
        ]
        mac_source = "".join(f"{len(v)}{v}" for v in mac_fields)
        secret = (self.s.azericard_secret_key or "").encode()
        if secret:
            payload["P_SIGN"] = hmac.new(secret, mac_source.encode(), hashlib.sha1).hexdigest().upper()
        return payload

    @property
    def gateway_url(self) -> str:
        return self.s.azericard_gateway_url or "https://testmpi.3dsecure.az/cgi-bin/cgi_link"

    def verify_callback(self, data: dict) -> bool:
        """Проверка ответа Azericard (упрощённо — наличие SUCCESS action)."""
        action = data.get("ACTION") or data.get("action")
        return action == "0"
