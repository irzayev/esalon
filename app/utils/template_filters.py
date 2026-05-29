"""Custom Jinja filters / globals."""
from datetime import datetime
from flask import Flask

from ..models.settings import Settings
from ..services.scheduling import utc_naive_to_local

AUDIT_ACTION_LABELS = {
    "order.create": "Создание заказа",
    "order.status": "Статус заказа",
    "inventory.move": "Движение склада",
    "inventory.consume": "Списание склада (заказ)",
    "inventory.consume_adjust": "Корректировка списания (заказ)",
    "user.create": "Создание пользователя",
    "user.update": "Изменение пользователя",
    "user.delete": "Удаление пользователя",
    "car.create": "Добавление автомобиля",
    "car.update": "Изменение автомобиля",
    "car.delete": "Удаление автомобиля",
    "settings.update": "Настройки",
    "branch.save": "Филиал",
    "backup.download": "Бэкап: скачивание",
    "backup.restore": "Бэкап: восстановление",
    "data.reset": "Сброс операционных данных",
}


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
        return AUDIT_ACTION_LABELS.get(code, code)

    @app.context_processor
    def inject_globals():
        try:
            settings = Settings.get()
        except Exception:
            settings = None
        return {"app_settings": settings, "now": datetime.utcnow()}
