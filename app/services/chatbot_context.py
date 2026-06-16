"""Chatbot template context helpers."""
from __future__ import annotations

from ..models.service import Service
from ..models.settings import Settings
from .branding import build_wa_context
from .chatbot_booking import default_branch
from .chatbot_defaults import (
    DEFAULT_MENU_BOOKING,
    DEFAULT_MENU_INFO,
    DEFAULT_MENU_OPERATOR,
)
from .wa_inbox import wa_operator_inbox_enabled


def build_menu_lines(settings: Settings | None = None) -> str:
    s = settings or Settings.get()
    info = (s.chatbot_menu_info_label or "").strip() or DEFAULT_MENU_INFO
    booking = (s.chatbot_menu_booking_label or "").strip() or DEFAULT_MENU_BOOKING
    operator = (s.chatbot_menu_operator_label or "").strip() or DEFAULT_MENU_OPERATOR
    lines = [f"1 — {info}", f"2 — {booking}"]
    if wa_operator_inbox_enabled(s):
        lines.append(f"3 — {operator}")
    return "\n".join(lines)


def build_chatbot_context(settings: Settings | None = None, **extra: str) -> dict[str, str]:
    s = settings or Settings.get()
    ctx = build_wa_context(s, **extra)
    branch = default_branch()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    currency = s.default_currency or "AZN"
    lines = [f"• {svc.name} — {svc.price:.0f} {currency}" for svc in services]
    ctx["services_list"] = "\n".join(lines) if lines else "—"
    if branch:
        ctx["work_hours"] = f"{branch.work_open} – {branch.work_close}"
    else:
        ctx["work_hours"] = ""
    ctx["branch_name"] = ctx.get("company", "")
    ctx["branch_address"] = ctx.get("address", "")
    ctx["menu_info"] = (s.chatbot_menu_info_label or "").strip() or DEFAULT_MENU_INFO
    ctx["menu_booking"] = (s.chatbot_menu_booking_label or "").strip() or DEFAULT_MENU_BOOKING
    ctx["menu_operator"] = (s.chatbot_menu_operator_label or "").strip() or DEFAULT_MENU_OPERATOR
    ctx["menu_lines"] = build_menu_lines(s)
    ctx["currency"] = currency
    ctx.update({k: str(v) for k, v in extra.items()})
    return ctx


def format_chatbot_message(
    template: str,
    settings: Settings | None = None,
    *,
    default: str = "",
    **extra: str,
) -> str:
    s = settings or Settings.get()
    tpl = (template or "").strip() or default
    ctx = build_chatbot_context(s, **extra)
    try:
        return tpl.format(**ctx).strip()
    except (KeyError, ValueError):
        return tpl
