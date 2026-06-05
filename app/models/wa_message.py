"""Stored WhatsApp messages for CRM inbox."""
from datetime import datetime

from ..extensions import db


class WaMessageDirection:
    IN = "in"
    OUT = "out"


class WaMessageSender:
    CLIENT = "client"
    BOT = "bot"
    OPERATOR = "operator"


class WaMessage(db.Model):
    __tablename__ = "wa_messages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("wa_chat_sessions.id"), nullable=False, index=True
    )
    phone = db.Column(db.String(20), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"))
    direction = db.Column(db.String(8), nullable=False)  # in | out
    sender_type = db.Column(db.String(16), nullable=False)  # client | bot | operator
    operator_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    session = db.relationship("WaChatSession", back_populates="messages")
    client = db.relationship("Client")
    operator_user = db.relationship("User")
