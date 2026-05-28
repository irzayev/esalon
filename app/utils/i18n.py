"""Lightweight i18n: AZ (default) and RU."""
from __future__ import annotations

from flask import g, has_request_context, session

from ..i18n.messages import MESSAGES, ORDER_STATUS_CLASSES
from ..models.settings import Settings

SUPPORTED_LOCALES = ("az", "ru")
DEFAULT_LOCALE = "az"
SESSION_KEY = "locale"
COOKIE_KEY = "washer-locale"


def _fallback_locale() -> str:
    try:
        lang = (Settings.get().default_language or DEFAULT_LOCALE).strip().lower()
    except Exception:
        lang = DEFAULT_LOCALE
    if lang not in SUPPORTED_LOCALES:
        return DEFAULT_LOCALE
    return lang


def get_locale() -> str:
    if has_request_context():
        if SESSION_KEY in session:
            loc = session[SESSION_KEY]
            if loc in SUPPORTED_LOCALES:
                return loc
        from flask import request

        cookie = (request.cookies.get(COOKIE_KEY) or "").strip().lower()
        if cookie in SUPPORTED_LOCALES:
            return cookie
    return _fallback_locale()


def set_locale(locale: str) -> str:
    loc = locale.strip().lower() if locale else DEFAULT_LOCALE
    if loc not in SUPPORTED_LOCALES:
        loc = DEFAULT_LOCALE
    if has_request_context():
        session[SESSION_KEY] = loc
    return loc


def translate(key: str, /, **kwargs) -> str:
    locale = get_locale()
    table = MESSAGES.get(locale) or MESSAGES[DEFAULT_LOCALE]
    text = table.get(key) or MESSAGES["ru"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def t(key: str, /, **kwargs) -> str:
    return translate(key, **kwargs)


def get_body_type_choices() -> list[tuple[str, str]]:
    from ..models.client import CarBodyType

    return [(t.value, translate(f"car.body.{t.value}")) for t in CarBodyType]


def translated_receipt_placeholders() -> list[tuple[str, str]]:
    from ..services.receipt import RECEIPT_PLACEHOLDERS

    result: list[tuple[str, str]] = []
    for placeholder, _default in RECEIPT_PLACEHOLDERS:
        slug = placeholder.strip("{}")
        result.append((placeholder, translate(f"receipt.ph.{slug}")))
    return result


def client_level_label(level: str) -> str:
    key = f"crm.level.{(level or 'regular').lower()}"
    label = translate(key)
    return label if label != key else level


def role_label(role: str) -> str:
    mapping = {
        "admin": "role.admin",
        "manager": "role.manager",
        "worker": "role.worker",
    }
    return translate(mapping.get(role, role))


def order_status_label(status: str) -> tuple[str, str]:
    key = f"order.status.{status}"
    label = translate(key)
    if label == key:
        label = status
    css = ORDER_STATUS_CLASSES.get(status, "bg-slate-100 text-slate-700")
    return label, css


def get_order_status_labels() -> dict:
    from ..models.order import OrderStatus

    return {st: order_status_label(st.value) for st in OrderStatus}


def init_i18n(app) -> None:
    @app.before_request
    def _set_locale():
        g.locale = get_locale()

    @app.context_processor
    def _inject_i18n():
        loc = get_locale()
        return {
            "_": translate,
            "t": translate,
            "locale": loc,
            "current_locale": loc,
            "statuses": get_order_status_labels(),
            "role_label": role_label,
            "client_level_label": client_level_label,
        }
