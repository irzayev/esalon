"""WhatsApp: напоминания по расписанию и ручная рассылка."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from ..extensions import db
from ..models.client import Client
from ..models.order import Order, OrderStatus
from ..models.settings import Settings
from .branding import DEFAULT_WA_REMINDER, DEFAULT_WA_STATUS_CHANGE, format_whatsapp_message
from .evolution_api import EvolutionAPIService

log = logging.getLogger(__name__)

COMPLETED_STATUSES = (OrderStatus.DONE.value, OrderStatus.DELIVERED.value)


def client_last_visit(client: Client) -> datetime | None:
    return (
        db.session.query(func.max(Order.completed_at))
        .filter(
            Order.client_id == client.id,
            Order.status.in_(COMPLETED_STATUSES),
            Order.completed_at.isnot(None),
        )
        .scalar()
    )


def clients_due_for_reminder(settings: Settings | None = None) -> list[Client]:
    s = settings or Settings.get()
    if not s.evolution_send_reminders:
        return []

    days = max(int(s.evolution_reminder_days or 30), 1)
    cutoff = datetime.utcnow() - timedelta(days=days)

    clients = (
        Client.query.filter(Client.phone.isnot(None), Client.phone != "")
        .order_by(Client.id)
        .all()
    )
    due: list[Client] = []
    for client in clients:
        last_visit = client_last_visit(client)
        if not last_visit or last_visit > cutoff:
            continue
        if client.wa_last_reminder_at and client.wa_last_reminder_at > cutoff:
            continue
        due.append(client)
    return due


def notify_order_status_change(order: Order, old_status: str) -> None:
    """WhatsApp клиенту при смене статуса заказа (если включено в настройках)."""
    if old_status == order.status:
        return
    s = Settings.get()
    if not (s.evolution_enabled and s.evolution_send_on_status_change):
        return
    if not order.client or not order.client.phone:
        return
    try:
        from ..utils.i18n import order_status_label

        svc = EvolutionAPIService(s)
        if not svc.enabled:
            return
        status_label, _ = order_status_label(order.status)
        msg = format_whatsapp_message(
            s.wa_template_status_change,
            s,
            default=DEFAULT_WA_STATUS_CHANGE,
            order_number=order.number,
            client_name=order.client.name,
            order_status=status_label,
        )
        svc.send_text(order.client.phone, msg)
    except Exception:
        log.exception("WA status change notify failed for order %s", order.number)


def send_text_to_client(
    client: Client,
    text: str,
    *,
    mark_reminder: bool = False,
) -> tuple[bool, str]:
    if not client.phone:
        return False, "У клиента нет телефона"
    svc = EvolutionAPIService()
    if not svc.enabled:
        return False, "Evolution API не настроен"
    ok, msg = svc.send_text(client.phone, text)
    if ok and mark_reminder:
        client.wa_last_reminder_at = datetime.utcnow()
    return ok, msg


def send_reminders(*, dry_run: bool = False) -> dict[str, int | str]:
    s = Settings.get()
    if not s.evolution_send_reminders:
        return {"skipped": 1, "reason": "reminders_disabled", "sent": 0, "failed": 0}

    svc = EvolutionAPIService(s)
    if not svc.enabled:
        return {"skipped": 1, "reason": "evolution_disabled", "sent": 0, "failed": 0}

    template = s.wa_template_reminder or DEFAULT_WA_REMINDER
    due = clients_due_for_reminder(s)
    sent = failed = 0

    for client in due:
        msg = format_whatsapp_message(
            template,
            s,
            default=DEFAULT_WA_REMINDER,
            client_name=client.name,
        )
        if dry_run:
            sent += 1
            continue
        ok, detail = send_text_to_client(client, msg, mark_reminder=True)
        if ok:
            sent += 1
        else:
            failed += 1
            log.warning("WA reminder failed for client %s: %s", client.id, detail)

    if not dry_run and (sent or failed):
        db.session.commit()

    return {"sent": sent, "failed": failed, "due": len(due), "dry_run": dry_run}


def resolve_template_body(template_key: str, settings: Settings | None = None) -> str | None:
    from ..utils.whatsapp_templates import template_body_by_key

    return template_body_by_key(template_key, settings)


def broadcast_message(
    template_key: str,
    client_ids: list[int] | None = None,
    *,
    mark_as_reminder: bool = False,
) -> dict[str, int]:
    s = Settings.get()
    body_tpl = resolve_template_body(template_key, s)
    if not body_tpl:
        return {"sent": 0, "failed": 0, "skipped": 0, "error": "unknown_template"}

    svc = EvolutionAPIService(s)
    if not svc.enabled:
        return {"sent": 0, "failed": 0, "skipped": 0, "error": "evolution_disabled"}

    q = Client.query.filter(Client.phone.isnot(None), Client.phone != "")
    if client_ids:
        q = q.filter(Client.id.in_(client_ids))
    clients = q.all()

    sent = failed = skipped = 0
    for client in clients:
        msg = format_whatsapp_message(
            body_tpl,
            s,
            default=body_tpl,
            client_name=client.name,
        )
        ok, _ = send_text_to_client(
            client,
            msg,
            mark_reminder=mark_as_reminder and template_key == "reminder",
        )
        if ok:
            sent += 1
        else:
            failed += 1

    if sent or failed:
        db.session.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped}
