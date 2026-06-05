"""Evolution API webhook for inbound WhatsApp messages."""
from __future__ import annotations

import logging

from flask import Blueprint, abort, jsonify, request

from ...extensions import csrf
from ...models.settings import Settings
from ...services.chatbot_booking import phone_from_evolution
from ...services.chatbot_engine import handle_incoming, send_reply

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


def _parse_inbound(msg: dict) -> tuple[str, str, str, bool] | None:
    key = msg.get("key") or {}
    if key.get("fromMe"):
        return None
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
    return phone, text, push_name, False


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

    processed = 0
    for msg in messages:
        parsed = _parse_inbound(msg)
        if not parsed:
            continue
        phone, text, push_name, _ = parsed
        try:
            reply = handle_incoming(phone, text, push_name)
            if reply:
                ok, detail = send_reply(phone, reply)
                if not ok:
                    log.warning("chatbot send failed for %s: %s", phone, detail)
            processed += 1
        except Exception:
            log.exception("chatbot handle_incoming failed for %s", phone)

    return jsonify({"status": "ok", "processed": processed}), 200
