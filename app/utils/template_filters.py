"""Custom Jinja filters / globals."""
from datetime import datetime
from flask import Flask

from ..models.settings import Settings
from ..services.scheduling import utc_naive_to_local
from .country_dial_codes import DEFAULT_DIAL_CODE, get_country_dial_codes

def register_filters(app: Flask) -> None:
    @app.template_filter("money")
    def money(value) -> str:
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            v = 0.0
        cur = Settings.get().default_currency or "AZN"
        sym = "₼" if cur.upper() in ("AZN", "₼") else cur
        return f"{v:,.2f}\u00a0{sym}".replace(",", " ")

    @app.template_filter("dt")
    def dt(value) -> str:
        if not value:
            return "—"
        if isinstance(value, datetime):
            local = utc_naive_to_local(value) or value
            return local.strftime("%d.%m.%Y %H:%M")
        return str(value)

    @app.template_filter("time_24")
    def time_24(value) -> str:
        if not value:
            return "—"
        if isinstance(value, datetime):
            local = utc_naive_to_local(value) or value
            return local.strftime("%H:%M")
        return str(value)

    @app.template_filter("d")
    def d(value) -> str:
        if not value:
            return "—"
        return value.strftime("%d.%m.%Y")

    @app.template_filter("audit_action")
    def audit_action(code: str) -> str:
        from .i18n import translate

        key = f"audit.{code}"
        label = translate(key)
        return label if label != key else code

    @app.template_filter("work_minutes_display")
    def work_minutes_display(minutes) -> str:
        from .i18n import translate

        if minutes is None:
            return "—"
        return translate("orders.work_time_minutes").format(n=int(minutes))

    @app.template_filter("datetime_local_input")
    def datetime_local_input(value) -> str:
        from ..services.promo_code import format_promo_datetime_local

        return format_promo_datetime_local(value)

    @app.template_filter("utc_unix")
    def utc_unix(value) -> int | None:
        if not value:
            return None
        from calendar import timegm

        if isinstance(value, datetime):
            return timegm(value.timetuple()) if value.tzinfo is None else int(value.timestamp())
        return None

    @app.context_processor
    def inject_globals():
        try:
            settings = Settings.get()
        except Exception:
            settings = None
        now_local = utc_naive_to_local(datetime.utcnow()) or datetime.utcnow()
        return {
            "app_settings": settings,
            "now": now_local,
            "country_dial_codes": get_country_dial_codes(),
            "default_phone_dial": DEFAULT_DIAL_CODE,
        }
