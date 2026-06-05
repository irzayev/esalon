"""CRM WhatsApp inbox: message storage, retention, queries."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from ..extensions import db
from ..models.client import Client
from ..models.settings import Settings
from ..models.wa_chat_session import WaChatSession
from ..models.wa_message import (
    WaMessage,
    WaMessageDirection,
    WaMessageSender,
)
from .chatbot_booking import find_or_create_client
from .evolution_api import EvolutionAPIService

log = logging.getLogger(__name__)


def message_retention_days(settings: Settings | None = None) -> int:
    s = settings or Settings.get()
    try:
        days = int(s.chatbot_message_retention_days if s.chatbot_message_retention_days is not None else 7)
    except (TypeError, ValueError):
        days = 7
    return max(0, min(days, 30))


def wa_operator_inbox_enabled(settings: Settings | None = None) -> bool:
    s = settings or Settings.get()
    return bool(
        s.chatbot_enabled
        and s.evolution_enabled
        and s.chatbot_wa_inbox_enabled
    )


def crm_inbox_enabled(settings: Settings | None = None) -> bool:
    s = settings or Settings.get()
    return bool(
        s.chatbot_enabled
        and s.evolution_enabled
        and s.chatbot_crm_inbox_enabled
    )


def retention_enabled(settings: Settings | None = None) -> bool:
    return crm_inbox_enabled(settings) and message_retention_days(settings) > 0


def chats_feature_enabled(settings: Settings | None = None) -> bool:
    return crm_inbox_enabled(settings)


def get_or_create_session(phone: str, push_name: str = "") -> WaChatSession:
    session = WaChatSession.query.filter_by(phone=phone).first()
    if session:
        return session
    client = find_or_create_client(phone, push_name)
    session = WaChatSession(phone=phone, client_id=client.id if client else None)
    db.session.add(session)
    db.session.flush()
    return session


def store_message(
    *,
    phone: str,
    body: str,
    direction: str,
    sender_type: str,
    push_name: str = "",
    operator_user_id: int | None = None,
    commit: bool = True,
) -> WaMessage | None:
    s = Settings.get()
    if not retention_enabled(s):
        return None
    text = (body or "").strip()
    if not text:
        return None

    session = get_or_create_session(phone, push_name)
    if push_name and session.client_id:
        client = db.session.get(Client, session.client_id)
        if client and client.name in ("", "WhatsApp"):
            client.name = push_name.strip()

    msg = WaMessage(
        session_id=session.id,
        phone=phone,
        client_id=session.client_id,
        direction=direction,
        sender_type=sender_type,
        operator_user_id=operator_user_id,
        body=text,
    )
    session.last_message_at = datetime.utcnow()
    db.session.add(msg)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return msg


def purge_expired_messages(settings: Settings | None = None) -> int:
    s = settings or Settings.get()
    days = message_retention_days(s)
    if days <= 0:
        deleted = WaMessage.query.delete()
        db.session.commit()
        return deleted

    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = (
        WaMessage.query.filter(WaMessage.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return deleted


def inbox_conversations(*, q: str = "", operator_only: bool = False) -> list[dict]:
    """Conversations with preview for CRM inbox list."""
    last_msg_sq = (
        db.session.query(
            WaMessage.session_id.label("sid"),
            func.max(WaMessage.id).label("last_id"),
        )
        .group_by(WaMessage.session_id)
        .subquery()
    )

    query = (
        db.session.query(WaChatSession, WaMessage)
        .outerjoin(last_msg_sq, WaChatSession.id == last_msg_sq.c.sid)
        .outerjoin(WaMessage, WaMessage.id == last_msg_sq.c.last_id)
        .order_by(WaChatSession.last_message_at.desc())
    )

    if operator_only:
        query = query.filter(WaChatSession.operator_mode.is_(True))

    if q:
        like = f"%{q}%"
        query = query.outerjoin(Client, WaChatSession.client_id == Client.id).filter(
            or_(
                WaChatSession.phone.ilike(like),
                Client.name.ilike(like),
            )
        )

    rows = query.all()
    result = []
    for session, last_msg in rows:
        if not last_msg and not session.operator_mode:
            continue
        unread = bool(
            last_msg
            and last_msg.direction == WaMessageDirection.IN
            and (
                not session.staff_last_read_at
                or last_msg.created_at > session.staff_last_read_at
            )
        )
        client = session.client
        result.append(
            {
                "session": session,
                "last_message": last_msg,
                "client_name": client.name if client else session.phone,
                "unread": unread,
            }
        )
    return result


def session_messages(session_id: int, after_id: int = 0) -> list[WaMessage]:
    q = WaMessage.query.filter_by(session_id=session_id)
    if after_id:
        q = q.filter(WaMessage.id > after_id)
    return q.order_by(WaMessage.created_at.asc(), WaMessage.id.asc()).all()


def mark_session_read(session: WaChatSession) -> None:
    session.staff_last_read_at = datetime.utcnow()
    db.session.commit()


def send_operator_reply(
    session: WaChatSession,
    text: str,
    *,
    user_id: int,
) -> tuple[bool, str]:
    s = Settings.get()
    svc = EvolutionAPIService(s)
    if not svc.enabled:
        return False, "Evolution API отключён"

    body = (text or "").strip()
    if not body:
        return False, "Пустое сообщение"

    ok, detail = svc.send_text(session.phone, body)
    if not ok:
        return False, detail

    session.operator_mode = True
    session.state = "operator"
    store_message(
        phone=session.phone,
        body=body,
        direction=WaMessageDirection.OUT,
        sender_type=WaMessageSender.OPERATOR,
        operator_user_id=user_id,
        commit=False,
    )
    db.session.commit()
    return True, ""


def release_to_bot(session: WaChatSession) -> None:
    session.operator_mode = False
    session.state = "menu"
    session.state_data = {}
    db.session.commit()
