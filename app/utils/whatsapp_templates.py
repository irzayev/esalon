"""Список шаблонов WhatsApp для UI (настройки, CRM)."""
from __future__ import annotations

from ..models.settings import Settings
from ..models.wa_template import WaMessageTemplate
from ..services.branding import (
    DEFAULT_WA_BOOKING,
    DEFAULT_WA_READY,
    DEFAULT_WA_REMINDER,
    DEFAULT_WA_PAYMENT,
)


def system_template_entries(settings: Settings | None = None) -> list[dict[str, str]]:
    s = settings or Settings.get()
    return [
        {
            "key": "booking",
            "name": "Запись / подтверждение",
            "body": (s.wa_template_booking or "").strip() or DEFAULT_WA_BOOKING,
            "kind": "system",
        },
        {
            "key": "ready",
            "name": "Услуга оказана",
            "body": (s.wa_template_ready or "").strip() or DEFAULT_WA_READY,
            "kind": "system",
        },
        {
            "key": "reminder",
            "name": "Напоминание «пора на салон»",
            "body": (s.wa_template_reminder or "").strip() or DEFAULT_WA_REMINDER,
            "kind": "system",
        },
        {
            "key": "payment",
            "name": "Ссылка на оплату (Azericard)",
            "body": (s.wa_template_payment or "").strip() or DEFAULT_WA_PAYMENT,
            "kind": "system",
        },
    ]


def custom_template_entries() -> list[dict[str, str]]:
    rows = (
        WaMessageTemplate.query.filter_by(is_active=True)
        .order_by(WaMessageTemplate.sort_order, WaMessageTemplate.name)
        .all()
    )
    return [
        {
            "key": f"custom:{t.id}",
            "name": t.name,
            "body": t.body,
            "kind": "custom",
            "id": t.id,
        }
        for t in rows
    ]


def all_template_entries(settings: Settings | None = None) -> list[dict[str, str]]:
    return system_template_entries(settings) + custom_template_entries()


_BROADCAST_SYSTEM_KEYS = frozenset({"reminder"})


def broadcast_template_entries(settings: Settings | None = None) -> list[dict[str, str]]:
    """Шаблоны для массовой рассылки: «пора на салон» + кастомные."""
    system = [
        e for e in system_template_entries(settings) if e["key"] in _BROADCAST_SYSTEM_KEYS
    ]
    return system + custom_template_entries()


def is_broadcast_template_key(template_key: str, settings: Settings | None = None) -> bool:
    return any(e["key"] == template_key for e in broadcast_template_entries(settings))


def template_body_by_key(template_key: str, settings: Settings | None = None) -> str | None:
    for entry in all_template_entries(settings):
        if entry["key"] == template_key:
            return entry["body"]
    return None
