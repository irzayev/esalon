"""Evolution API webhook for inbound WhatsApp messages."""
from __future__ import annotations

import logging

from flask import Blueprint, abort, jsonify, request

from ...extensions import csrf, db
from ...models.settings import Settings
from ...models.wa_message import WaMessageDirection, WaMessageSender
from ...services.chatbot_booking import phone_from_evolution
from ...services.chatbot_engine import handle_incoming, send_reply
from ...services.wa_inbox import (
    crm_inbox_enabled,
    purge_expired_messages,
    retention_enabled,
    store_message,
)

log = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__)


def _extract_messages(payload: dict | list) -> list[dict]:
    """Normalize Evolution webhook payloads across API versions."""
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    if not isinstance(payload, dict):
        return []

    event = (payload.get("event") or "").lower()
    data = payload.get("data")
    if event in ("messages.upsert", "messages_upsert", "message") and data is not None:
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        if isinstance(data, dict):
            return [data]
    if "key" in payload and "message" in payload:
        return [payload]
    return []


def _message_text(message: dict) -> str:
    if not isinstance(message, dict):
        return ""
    if message.get("conversation"):
        return str(message["conversation"])
    ext = message.get("extendedTextMessage") or {}
    if ext.get("text"):
        return str(ext["text"])
    btn = message.get("buttonsResponseMessage") or {}
    if btn.get("selectedDisplayText"):
        return str(btn["selectedDisplayText"])
    lst = message.get("listResponseMessage") or {}
    if lst.get("title"):
        return str(lst["title"])
    return ""


def _parse_message(msg: dict) -> tuple[str, str, str, bool] | None:
    key = msg.get("key") or {}
    remote = key.get("remoteJid") or key.get("remote_jid") or ""
    if not remote or remote.endswith("@g.us"):
        return None
    phone_raw = str(remote).split("@")[0]
    settings = Settings.get()
    phone = phone_from_evolution(phone_raw, settings)
    if not phone:
        return None
    message = msg.get("message") or msg
    text = _message_text(message)
    if not text:
        return None
    push_name = str(msg.get("pushName") or msg.get("push_name") or "").strip()
    from_me = bool(key.get("fromMe"))
    return phone, text, push_name, from_me


def _verify_secret() -> bool:
    settings = Settings.get()
    secret = (settings.chatbot_webhook_secret or "").strip()
    if not secret:
        return False
    token = (
        request.args.get("secret")
        or request.headers.get("X-Webhook-Secret")
        or request.headers.get("apikey")
        or ""
    ).strip()
    return token == secret


@bp.post("/evolution")
@csrf.exempt
def evolution_webhook():
    settings = Settings.get()
    if not settings.chatbot_enabled:
        return jsonify({"status": "disabled"}), 200
    if not _verify_secret():
        abort(403)

    payload = request.get_json(silent=True) or {}
    messages = _extract_messages(payload)
    if not messages:
        return jsonify({"status": "ignored"}), 200

    store_enabled = retention_enabled(settings)
    processed = 0

    for msg in messages:
        parsed = _parse_message(msg)
        if not parsed:
            continue
        phone, text, push_name, from_me = parsed

        try:
            if from_me:
                if store_enabled:
                    store_message(
                        phone=phone,
                        body=text,
                        direction=WaMessageDirection.OUT,
                        sender_type=WaMessageSender.OPERATOR,
                        commit=True,
                    )
                processed += 1
                continue

            if store_enabled:
                store_message(
                    phone=phone,
                    body=text,
                    direction=WaMessageDirection.IN,
                    sender_type=WaMessageSender.CLIENT,
                    push_name=push_name,
                    commit=False,
                )

            reply = handle_incoming(phone, text, push_name)
            if reply:
                ok, detail = send_reply(phone, reply)
                if not ok:
                    log.warning("chatbot send failed for %s: %s", phone, detail)
                elif store_enabled:
                    store_message(
                        phone=phone,
                        body=reply,
                        direction=WaMessageDirection.OUT,
                        sender_type=WaMessageSender.BOT,
                        commit=False,
                    )
            db.session.commit()
            processed += 1
        except Exception:
            db.session.rollback()
            log.exception("chatbot handle_incoming failed for %s", phone)

    if crm_inbox_enabled(settings):
        try:
            purge_expired_messages(settings)
        except Exception:
            log.exception("wa message purge failed")

    return jsonify({"status": "ok", "processed": processed}), 200
