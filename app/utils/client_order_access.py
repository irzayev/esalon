"""Client mini-auth: phone + order number, session-scoped access."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import session

from ..models.order import Order
from .client_fields import normalize_phone, validate_phone
from .order_lookup import is_valid_order_number

SESSION_KEY = "client_order_access"
ACCESS_TTL = timedelta(hours=24)

CLIENT_VISIBLE_AUDIT_ACTIONS = frozenset(
    {
        "order.status",
        "order.payment",
        "order.payment_online_failed",
        "order.schedule",
    }
)


def _access_map() -> dict:
    raw = session.get(SESSION_KEY)
    return raw if isinstance(raw, dict) else {}


def grant_client_order_access(number: str, phone: str) -> None:
    data = _access_map()
    data[number] = {
        "phone": phone,
        "exp": (datetime.utcnow() + ACCESS_TTL).isoformat(),
    }
    session[SESSION_KEY] = data
    session.modified = True


def revoke_client_order_access(number: str | None = None) -> None:
    if number is None:
        session.pop(SESSION_KEY, None)
    else:
        data = _access_map()
        data.pop(number, None)
        session[SESSION_KEY] = data
    session.modified = True


def has_client_order_access(number: str) -> bool:
    entry = _access_map().get(number)
    if not entry:
        return False
    exp_raw = entry.get("exp")
    if not exp_raw:
        return False
    try:
        exp = datetime.fromisoformat(exp_raw)
    except (TypeError, ValueError):
        return False
    if datetime.utcnow() >= exp:
        revoke_client_order_access(number)
        return False
    return True


def verify_order_credentials(number: str, phone_raw: str) -> tuple[Order | None, str]:
    """Return (order, error_message). Generic error on mismatch."""
    number = (number or "").strip()
    phone = normalize_phone(phone_raw)
    ok, err = validate_phone(phone)
    if not ok:
        return None, err
    if not is_valid_order_number(number):
        return None, "track.error.invalid"
    order = Order.query.filter_by(number=number).first()
    if not order or not order.client or order.client.phone != phone:
        return None, "track.error.invalid"
    return order, ""


def get_client_audit_logs(order_id: int, *, limit: int = 50):
    from ..models.audit import AuditLog

    return (
        AuditLog.query.filter(
            AuditLog.entity == "order",
            AuditLog.entity_id == order_id,
            AuditLog.action.in_(CLIENT_VISIBLE_AUDIT_ACTIONS),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
