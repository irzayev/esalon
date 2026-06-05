"""CRM WhatsApp inbox routes (managers and admins only)."""
from __future__ import annotations

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ...extensions import db
from ...models.wa_chat_session import WaChatSession
from ...models.wa_message import WaMessageDirection, WaMessageSender
from ...utils.audit import log_audit
from ...utils.decorators import manager_required
from ...services.wa_inbox import (
    chats_feature_enabled,
    inbox_conversations,
    mark_session_read,
    release_to_bot,
    send_operator_reply,
    session_messages,
)
from .routes import bp


def _require_chats_enabled():
    if not chats_feature_enabled():
        abort(404)


def _get_session(session_id: int) -> WaChatSession:
    session = db.session.get(WaChatSession, session_id)
    if not session:
        abort(404)
    return session


def _message_to_dict(msg) -> dict:
    from ...utils.i18n import translate

    operator_name = ""
    if msg.operator_user:
        operator_name = msg.operator_user.name
    sender_label = msg.sender_type
    if msg.sender_type == WaMessageSender.BOT:
        sender_label = translate("crm.chats.sender_bot")
    elif msg.sender_type == WaMessageSender.OPERATOR:
        sender_label = operator_name or translate("crm.chats.sender_operator")
    elif msg.sender_type == WaMessageSender.CLIENT:
        sender_label = translate("crm.chats.sender_client")

    return {
        "id": msg.id,
        "body": msg.body,
        "direction": msg.direction,
        "sender_type": msg.sender_type,
        "sender_label": sender_label,
        "created_at": msg.created_at.isoformat() if msg.created_at else "",
        "created_display": msg.created_at.strftime("%d.%m.%Y %H:%M") if msg.created_at else "",
    }


@bp.route("/chats")
@login_required
@manager_required
def chats():
    _require_chats_enabled()
    q = (request.args.get("q") or "").strip()
    operator_only = request.args.get("operator") == "1"
    session_id = request.args.get("session", type=int)

    conversations = inbox_conversations(q=q, operator_only=operator_only)
    active = None
    messages = []
    if session_id:
        active = _get_session(session_id)
        messages = session_messages(session_id)
        mark_session_read(active)

    return render_template(
        "crm/chats.html",
        conversations=conversations,
        active=active,
        messages=messages,
        q=q,
        operator_only=operator_only,
        session_id=session_id,
    )


@bp.route("/chats/<int:session_id>")
@login_required
@manager_required
def chat_detail(session_id: int):
    _require_chats_enabled()
    return redirect(
        url_for(
            "crm.chats",
            session=session_id,
            q=request.args.get("q") or None,
            operator=request.args.get("operator") or None,
        )
    )


@bp.route("/chats/<int:session_id>/messages")
@login_required
@manager_required
def chat_messages_poll(session_id: int):
    _require_chats_enabled()
    session = _get_session(session_id)
    after_id = request.args.get("after", type=int) or 0
    msgs = session_messages(session_id, after_id=after_id)
    if msgs:
        mark_session_read(session)
    return jsonify({"messages": [_message_to_dict(m) for m in msgs]})


@bp.post("/chats/<int:session_id>/send")
@login_required
@manager_required
def chat_send(session_id: int):
    _require_chats_enabled()
    session = _get_session(session_id)
    text = (request.form.get("body") or "").strip()
    if not text:
        from ...utils.i18n import translate
        flash_msg = translate("crm.chats.empty_message")
        return redirect(url_for("crm.chats", session=session_id, q=request.form.get("q") or None))

    ok, err = send_operator_reply(session, text, user_id=current_user.id)
    from ...utils.i18n import translate

    if ok:
        log_audit(
            "wa_inbox.send",
            entity="wa_chat_session",
            entity_id=session.id,
            details=session.phone,
        )
        db.session.commit()
        flash(translate("crm.chats.sent"), "success")
    else:
        flash(err or translate("crm.chats.send_failed"), "error")

    return redirect(
        url_for(
            "crm.chats",
            session=session_id,
            q=request.form.get("q") or None,
            operator=request.form.get("operator") or None,
        )
    )


@bp.post("/chats/<int:session_id>/release")
@login_required
@manager_required
def chat_release(session_id: int):
    _require_chats_enabled()
    session = _get_session(session_id)
    release_to_bot(session)
    log_audit(
        "wa_inbox.release",
        entity="wa_chat_session",
        entity_id=session.id,
        details=session.phone,
    )
    db.session.commit()
    from ...utils.i18n import translate

    flash(translate("crm.chats.released"), "success")
    return redirect(
        url_for(
            "crm.chats",
            session=session_id,
            q=request.form.get("q") or None,
            operator=request.form.get("operator") or None,
        )
    )
