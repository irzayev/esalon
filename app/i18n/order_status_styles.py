"""Unified order status colors (background, text) for badges and filters."""

from typing import Final

# status key -> (background, text)
ORDER_STATUS_COLORS: Final[dict[str, tuple[str, str]]] = {
    "new": ("#f1f5f9", "#334155"),
    "booked": ("#eff6ff", "#2563eb"),
    "in_progress": ("#fffbeb", "#b45309"),
    "waiting": ("#faf5ff", "#9333ea"),
    "done": ("#ecfdf5", "#047857"),
    "delivered": ("#183373", "#ffffff"),
    "canceled": ("#fff1f2", "#be123c"),
}

_STATUS_MODIFIERS: Final[dict[str, str]] = {
    "new": "new",
    "booked": "booked",
    "in_progress": "in-progress",
    "waiting": "waiting",
    "done": "done",
    "delivered": "delivered",
    "canceled": "canceled",
}

ORDER_STATUS_CLASSES: Final[dict[str, str]] = {
    key: f"order-status--{mod}" for key, mod in _STATUS_MODIFIERS.items()
}

DEFAULT_ORDER_STATUS_CLASS = "order-status--unknown"
