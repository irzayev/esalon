"""Rule-based WhatsApp chatbot FSM."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..extensions import db
from ..models.chatbot_rule import ChatbotRule
from ..models.settings import Settings
from ..models.wa_chat_session import WaChatSession
from .chatbot_booking import (
    AvailableSlot,
    MenuServiceItem,
    available_slots,
    create_booking,
    default_branch,
    find_or_create_client,
    format_date_display,
    format_services_menu,
    format_slots_menu,
    list_services_for_menu,
    parse_user_date,
    utc_to_local_time_label,
)
from .chatbot_context import build_chatbot_context, format_chatbot_message
from .chatbot_defaults import (
    DEFAULT_CHATBOT_CONFIRM,
    DEFAULT_CHATBOT_ERROR,
    DEFAULT_CHATBOT_NO_SLOTS,
    DEFAULT_CHATBOT_OPERATOR_UNAVAILABLE,
    DEFAULT_CHATBOT_SELECT_DATE,
    DEFAULT_CHATBOT_SELECT_SERVICE,
    DEFAULT_CHATBOT_SELECT_TIME,
    DEFAULT_CHATBOT_SUCCESS,
    DEFAULT_CHATBOT_WELCOME,
    DEFAULT_MENU_BOOKING,
    DEFAULT_MENU_INFO,
    DEFAULT_MENU_OPERATOR,
)
from .branding import client_order_track_url
from .chatbot_operator import request_operator
from .evolution_api import EvolutionAPIService
from .wa_inbox import wa_operator_inbox_enabled

log = logging.getLogger(__name__)

MENU_KEYWORDS = frozenset({"menyu", "menu", "0", "start", "geri", "назад", "меню", "старт"})
YES_KEYWORDS = frozenset({
    "bəli", "beli", "yes", "ok", "təsdiq", "tesdiq", "təsdiqləyirəm", "tesdiqleyirem",
    "да", "подтверждаю", "подтвердить",
})
NO_KEYWORDS = frozenset({
    "xeyr", "no", "ləğv", "legv", "ləğv et", "legv et",
    "нет", "отмена", "отменить",
})

_rate_buckets: dict[str, list[float]] = {}
_RATE_LIMIT = 20
_RATE_WINDOW_SEC = 60


def _rate_limited(phone: str) -> bool:
    now = datetime.utcnow().timestamp()
    bucket = _rate_buckets.setdefault(phone, [])
    cutoff = now - _RATE_WINDOW_SEC
    _rate_buckets[phone] = [t for t in bucket if t >= cutoff]
    if len(_rate_buckets[phone]) >= _RATE_LIMIT:
        return True
    _rate_buckets[phone].append(now)
    return False


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _is_menu_command(text: str) -> bool:
    return _norm(text) in MENU_KEYWORDS


def _get_session(phone: str) -> WaChatSession:
    session = WaChatSession.query.filter_by(phone=phone).first()
    if not session:
        session = WaChatSession(phone=phone, state="idle")
        db.session.add(session)
        db.session.flush()
    return session


def _session_expired(session: WaChatSession, settings: Settings) -> bool:
    hours = max(int(settings.chatbot_session_timeout_hours or 24), 1)
    if not session.last_message_at:
        return False
    return datetime.utcnow() - session.last_message_at > timedelta(hours=hours)


def _reset_session(session: WaChatSession) -> None:
    session.state = "menu"
    session.operator_mode = False
    session.state_data = {}


def _match_info_rule(text: str) -> ChatbotRule | None:
    normalized = _norm(text)
    if not normalized:
        return None
    rules = (
        ChatbotRule.query.filter_by(is_active=True)
        .order_by(ChatbotRule.sort_order, ChatbotRule.id)
        .all()
    )
    for rule in rules:
        if rule.rule_type != "info":
            continue
        for trigger in rule.trigger_list():
            if trigger == normalized or trigger in normalized:
                return rule
    return None


def _menu_labels(settings: Settings) -> tuple[str, str, str]:
    info = (settings.chatbot_menu_info_label or "").strip() or DEFAULT_MENU_INFO
    booking = (settings.chatbot_menu_booking_label or "").strip() or DEFAULT_MENU_BOOKING
    operator = (settings.chatbot_menu_operator_label or "").strip() or DEFAULT_MENU_OPERATOR
    return info, booking, operator


def _welcome_message(settings: Settings) -> str:
    return format_chatbot_message(
        settings.chatbot_welcome_message,
        settings,
        default=DEFAULT_CHATBOT_WELCOME,
    )


def _menu_choice(text: str, settings: Settings) -> str | None:
    normalized = _norm(text)
    info, booking, operator = _menu_labels(settings)
    if normalized in ("1", info.lower()):
        return "info"
    if normalized in ("2", booking.lower(), "yazı", "yazi", "rezervasiya", "bron", "запись", "бронь", "бронирование"):
        return "booking"
    if wa_operator_inbox_enabled(settings) and normalized in (
        "3",
        operator.lower(),
        "operator",
        "оператор",
        "человек",
    ):
        return "operator"
    return None


def _operator_intent(text: str, settings: Settings) -> bool:
    normalized = _norm(text)
    _, _, operator = _menu_labels(settings)
    return normalized in (
        "3",
        operator.lower(),
        "operator",
        "оператор",
        "человек",
    )


def _operator_unavailable_message(settings: Settings) -> str:
    return format_chatbot_message(
        "",
        settings,
        default=DEFAULT_CHATBOT_OPERATOR_UNAVAILABLE,
    )


def _menu_help_message(settings: Settings) -> str:
    opts = "1, 2"
    if wa_operator_inbox_enabled(settings):
        opts += " və ya 3"
    return f"Menyu seçin ({opts}) və ya «menyu» yazın."


def _load_menu_items(session: WaChatSession) -> list[MenuServiceItem]:
    data = session.state_data
    cached = data.get("menu_items")
    if cached:
        return [
            MenuServiceItem(
                kind=i["kind"],
                id=int(i["id"]),
                name=i["name"],
                price=float(i["price"]),
                duration_min=int(i["duration_min"]),
                required_bay_types=set(i.get("required_bay_types") or []),
            )
            for i in cached
        ]
    items = list_services_for_menu()
    session.state_data = {
        **data,
        "menu_items": [
            {
                "kind": i.kind,
                "id": i.id,
                "name": i.name,
                "price": i.price,
                "duration_min": i.duration_min,
                "required_bay_types": list(i.required_bay_types),
            }
            for i in items
        ],
    }
    return items


def _load_slots(session: WaChatSession) -> list[AvailableSlot]:
    data = session.state_data
    cached = data.get("slots")
    if cached:
        return [
            AvailableSlot(
                index=int(s["index"]),
                time_label=s["time_label"],
                scheduled_at=datetime.fromisoformat(s["scheduled_at"]),
                bay_id=int(s["bay_id"]),
                date_str=s["date_str"],
            )
            for s in cached
        ]
    return []


def _store_slots(session: WaChatSession, slots: list[AvailableSlot]) -> None:
    data = session.state_data
    session.state_data = {
        **data,
        "slots": [
            {
                "index": s.index,
                "time_label": s.time_label,
                "scheduled_at": s.scheduled_at.isoformat(),
                "bay_id": s.bay_id,
                "date_str": s.date_str,
            }
            for s in slots
        ],
    }


def _handle_info(settings: Settings, session: WaChatSession, text: str) -> str:
    rule = _match_info_rule(text)
    if rule:
        reply = format_chatbot_message(rule.response_template, settings, default=rule.response_template)
        return f"{reply}\n\n{_welcome_message(settings)}"
    items = list_services_for_menu()
    menu = format_services_menu(items, settings.default_currency or "AZN")
    ctx = build_chatbot_context(settings, services_menu=menu)
    fallback = (
        f"{ctx['company']}\n"
        f"Ünvan: {ctx['address']}\n"
        f"Telefon: {ctx['phone']}\n"
        f"İş saatları: {ctx['work_hours']}\n\n"
        f"Xidmətlər:\n{ctx['services_list']}"
    )
    return f"{fallback}\n\n{_welcome_message(settings)}"


def _start_booking(settings: Settings, session: WaChatSession) -> str:
    items = _load_menu_items(session)
    if not items:
        session.state = "menu"
        return "Yazı üçün mövcud xidmət yoxdur.\n\n" + _welcome_message(settings)
    session.state = "booking_service"
    menu = format_services_menu(items, settings.default_currency or "AZN")
    return format_chatbot_message(
        settings.chatbot_tpl_booking_select_service,
        settings,
        default=DEFAULT_CHATBOT_SELECT_SERVICE,
        services_menu=menu,
    )


def _handle_booking_service(settings: Settings, session: WaChatSession, text: str) -> str:
    if _is_menu_command(text):
        _reset_session(session)
        return _welcome_message(settings)
    try:
        choice = int(text.strip())
    except ValueError:
        return "Siyahıdakı xidmətin nömrəsi ilə cavab verin və ya 0 — menyuya."
    items = _load_menu_items(session)
    if choice < 1 or choice > len(items):
        return "Yanlış nömrə. Siyahıdan xidmət seçin."
    item = items[choice - 1]
    session.state = "booking_date"
    session.state_data = {
        **session.state_data,
        "item_kind": item.kind,
        "item_id": item.id,
        "service_name": item.name,
        "price": item.price,
        "duration_min": item.duration_min,
        "required_bay_types": list(item.required_bay_types),
    }
    return format_chatbot_message(
        settings.chatbot_tpl_booking_select_date,
        settings,
        default=DEFAULT_CHATBOT_SELECT_DATE,
    )


def _handle_booking_date(settings: Settings, session: WaChatSession, text: str) -> str:
    if _is_menu_command(text):
        _reset_session(session)
        return _welcome_message(settings)
    day = parse_user_date(text)
    if not day:
        return "Tarix formatı yanlışdır. dd.mm.yyyy göstərin."
    from .scheduling import app_timezone

    if day < datetime.now(app_timezone()).date():
        return "Keçmiş tarix seçilə bilməz. Başqa tarix göstərin."

    branch = default_branch()
    if not branch:
        _reset_session(session)
        return "Filial konfiqurasiya edilməyib.\n\n" + _welcome_message(settings)

    data = session.state_data
    duration = int(data.get("duration_min") or 60)
    required = set(data.get("required_bay_types") or [])
    slots = available_slots(branch.id, day, duration, required)
    if not slots:
        return format_chatbot_message(
            settings.chatbot_tpl_booking_no_slots,
            settings,
            default=DEFAULT_CHATBOT_NO_SLOTS,
        )

    session.state = "booking_time"
    session.state_data = {
        **data,
        "booking_date": day.isoformat(),
        "date_display": format_date_display(day),
    }
    _store_slots(session, slots)
    return format_chatbot_message(
        settings.chatbot_tpl_booking_select_time,
        settings,
        default=DEFAULT_CHATBOT_SELECT_TIME,
        date=format_date_display(day),
        slots_menu=format_slots_menu(slots),
    )


def _handle_booking_time(settings: Settings, session: WaChatSession, text: str) -> str:
    if _is_menu_command(text):
        _reset_session(session)
        return _welcome_message(settings)
    try:
        choice = int(text.strip())
    except ValueError:
        return "Siyahıdakı vaxtın nömrəsi ilə cavab verin."
    slots = _load_slots(session)
    match = next((s for s in slots if s.index == choice), None)
    if not match:
        return "Yanlış nömrə. Siyahıdan vaxt seçin."

    data = session.state_data
    session.state = "booking_confirm"
    session.state_data = {
        **data,
        "scheduled_at": match.scheduled_at.isoformat(),
        "bay_id": match.bay_id,
        "time_label": match.time_label,
    }
    return format_chatbot_message(
        settings.chatbot_tpl_booking_confirm,
        settings,
        default=DEFAULT_CHATBOT_CONFIRM,
        service_name=data.get("service_name", ""),
        price=data.get("price", ""),
        currency=settings.default_currency or "AZN",
        date=data.get("date_display", ""),
        time=match.time_label,
    )


def _handle_booking_confirm(
    settings: Settings,
    session: WaChatSession,
    text: str,
    *,
    phone: str,
    client_name: str,
) -> str:
    normalized = _norm(text)
    if _is_menu_command(text) or normalized in NO_KEYWORDS:
        _reset_session(session)
        return "Yazı ləğv edildi.\n\n" + _welcome_message(settings)
    if normalized not in YES_KEYWORDS:
        return "Təsdiqləmək üçün BƏLİ, ləğv etmək üçün XEYR yazın."

    data = session.state_data
    try:
        scheduled_at = datetime.fromisoformat(data["scheduled_at"])
        bay_id = int(data["bay_id"])
        duration = int(data.get("duration_min") or 60)
    except (KeyError, TypeError, ValueError):
        _reset_session(session)
        return format_chatbot_message(
            settings.chatbot_tpl_booking_error,
            settings,
            default=DEFAULT_CHATBOT_ERROR,
            error="sessiya məlumatları köhnəlib",
        )

    order, err = create_booking(
        phone=phone,
        client_name=client_name,
        item_kind=data.get("item_kind", "service"),
        item_id=int(data.get("item_id") or 0),
        scheduled_at=scheduled_at,
        bay_id=bay_id,
        duration_min=duration,
    )
    _reset_session(session)
    if err or not order:
        return format_chatbot_message(
            settings.chatbot_tpl_booking_error,
            settings,
            default=DEFAULT_CHATBOT_ERROR,
            error=err or "naməlum xəta",
        )
    return format_chatbot_message(
        settings.chatbot_tpl_booking_success,
        settings,
        default=DEFAULT_CHATBOT_SUCCESS,
        order_number=order.number,
        order_link=client_order_track_url(order.number),
        service_name=data.get("service_name", ""),
        date=data.get("date_display", ""),
        time=data.get("time_label", utc_to_local_time_label(scheduled_at)),
    )


def handle_incoming(phone: str, text: str, push_name: str = "") -> str | None:
    """Process inbound WhatsApp message. Returns reply text or None."""
    settings = Settings.get()
    if not settings.chatbot_enabled or not settings.evolution_enabled:
        return None

    if _rate_limited(phone):
        log.warning("chatbot rate limit for %s", phone)
        return None

    session = _get_session(phone)
    client = find_or_create_client(phone, push_name)
    if client and not session.client_id:
        session.client_id = client.id
        if push_name and client.name in ("", "WhatsApp"):
            client.name = push_name.strip()

    if _session_expired(session, settings):
        _reset_session(session)

    session.touch()
    incoming = (text or "").strip()
    if not incoming:
        return None

    if session.operator_mode:
        if _is_menu_command(incoming):
            _reset_session(session)
            db.session.commit()
            return _welcome_message(settings)
        db.session.commit()
        return None

    if _is_menu_command(incoming):
        _reset_session(session)
        db.session.commit()
        return _welcome_message(settings)

    rule = _match_info_rule(incoming)
    if rule and session.state in ("idle", "menu", "info"):
        session.state = "menu"
        reply = format_chatbot_message(rule.response_template, settings, default=rule.response_template)
        db.session.commit()
        return f"{reply}\n\n{_welcome_message(settings)}"

    if session.state == "idle":
        session.state = "menu"
        db.session.commit()
        return _welcome_message(settings)

    if session.state == "menu":
        choice = _menu_choice(incoming, settings)
        if choice == "info":
            session.state = "info"
            reply = _handle_info(settings, session, incoming)
            db.session.commit()
            return reply
        if choice == "booking":
            reply = _start_booking(settings, session)
            db.session.commit()
            return reply
        if choice == "operator":
            if not wa_operator_inbox_enabled(settings):
                db.session.commit()
                return _operator_unavailable_message(settings)
            name = push_name or (client.name if client else "")
            reply = request_operator(session, last_message=incoming, client_name=name)
            if not reply:
                db.session.commit()
                return _operator_unavailable_message(settings)
            db.session.commit()
            return reply
        if _operator_intent(incoming, settings):
            db.session.commit()
            return _operator_unavailable_message(settings)
        db.session.commit()
        return _menu_help_message(settings)

    if session.state == "booking_service":
        reply = _handle_booking_service(settings, session, incoming)
        db.session.commit()
        return reply
    if session.state == "booking_date":
        reply = _handle_booking_date(settings, session, incoming)
        db.session.commit()
        return reply
    if session.state == "booking_time":
        reply = _handle_booking_time(settings, session, incoming)
        db.session.commit()
        return reply
    if session.state == "booking_confirm":
        reply = _handle_booking_confirm(
            settings,
            session,
            incoming,
            phone=phone,
            client_name=push_name or (client.name if client else ""),
        )
        db.session.commit()
        return reply
    if session.state == "info":
        reply = _handle_info(settings, session, incoming)
        db.session.commit()
        return reply

    _reset_session(session)
    db.session.commit()
    return _welcome_message(settings)


def send_reply(phone: str, text: str) -> tuple[bool, str]:
    svc = EvolutionAPIService()
    return svc.send_text(phone, text)
