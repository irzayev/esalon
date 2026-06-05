"""Operator handoff for WhatsApp chatbot."""
from __future__ import annotations

import re

from ..models.settings import Settings
from ..models.wa_chat_session import WaChatSession
from .chatbot_context import format_chatbot_message
from .chatbot_defaults import (
    DEFAULT_CHATBOT_OPERATOR_MESSAGE,
    DEFAULT_CHATBOT_OPERATOR_NOTIFY,
)
from .evolution_api import EvolutionAPIService


def request_operator(
    session: WaChatSession,
    *,
    last_message: str = "",
    client_name: str = "",
) -> str:
    """Switch session to operator mode and notify staff. Returns client message."""
    s = Settings.get()
    session.operator_mode = True
    session.state = "operator"

    client_msg = format_chatbot_message(
        s.chatbot_operator_message,
        s,
        default=DEFAULT_CHATBOT_OPERATOR_MESSAGE,
        client_name=client_name or session.phone,
    )

    notify_tpl = (s.chatbot_operator_notify_template or "").strip() or DEFAULT_CHATBOT_OPERATOR_NOTIFY
    notify_text = format_chatbot_message(
        notify_tpl,
        s,
        default=DEFAULT_CHATBOT_OPERATOR_NOTIFY,
        client_name=client_name or session.phone,
        phone=session.phone,
        last_message=(last_message or "")[:500],
    )

    svc = EvolutionAPIService(s)
    if svc.enabled:
        for raw in (s.chatbot_operator_phones or "").split(","):
            phone = raw.strip()
            if phone:
                svc.send_text(phone, notify_text)

    return client_msg


def parse_operator_phones(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]+", raw or "") if p.strip()]
