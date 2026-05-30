"""Flask URL converter for DDMMYYNN order numbers."""
from werkzeug.routing import BaseConverter

from .order_lookup import ORDER_NUMBER_RE


class OrderNumberConverter(BaseConverter):
    regex = ORDER_NUMBER_RE


def register_url_converters(app) -> None:
    app.url_map.converters["order_number"] = OrderNumberConverter
