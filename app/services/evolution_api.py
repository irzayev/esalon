"""Evolution API (WhatsApp) client.

Документация: https://doc.evolution-api.com/
Базовые методы: sendText, sendMedia, instance status.
"""
from __future__ import annotations
import logging
import re

import requests

from ..models.settings import Settings

log = logging.getLogger(__name__)


class EvolutionAPIService:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings.get()

    @property
    def enabled(self) -> bool:
        return bool(
            self.s.evolution_enabled
            and self.s.evolution_base_url
            and self.s.evolution_api_key
            and self.s.evolution_instance_name
        )

    def _headers(self) -> dict:
        return {
            "apikey": self.s.evolution_api_key,
            "Content-Type": "application/json",
        }

    def _normalize_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone or "")
        if not digits:
            return ""
        cc = self.s.evolution_default_country_code or "994"
        if not digits.startswith(cc) and len(digits) <= 10:
            digits = cc + digits.lstrip("0")
        return digits

    def send_text(self, phone: str, text: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, "Evolution API отключён в настройках"
        number = self._normalize_phone(phone)
        if not number:
            return False, "Некорректный номер"

        url = f"{self.s.evolution_base_url.rstrip('/')}/message/sendText/{self.s.evolution_instance_name}"
        body = {"number": number, "text": text}
        try:
            r = requests.post(url, json=body, headers=self._headers(), timeout=15)
            ok = r.status_code in (200, 201)
            return ok, r.text[:500]
        except requests.RequestException as e:
            log.exception("Evolution send_text failed")
            return False, str(e)

    def instance_status(self) -> tuple[bool, str]:
        if not (self.s.evolution_base_url and self.s.evolution_api_key and self.s.evolution_instance_name):
            return False, "Не заполнены поля интеграции"
        url = (
            f"{self.s.evolution_base_url.rstrip('/')}/instance/connectionState/"
            f"{self.s.evolution_instance_name}"
        )
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            return r.ok, r.text[:500]
        except requests.RequestException as e:
            return False, str(e)
