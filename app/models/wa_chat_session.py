"""WhatsApp chatbot conversation state per client phone."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..extensions import db


class WaChatSession(db.Model):
    __tablename__ = "wa_chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"))
    state = db.Column(db.String(40), nullable=False, default="idle")
    state_data_json = db.Column(db.Text, default="{}")
    operator_mode = db.Column(db.Boolean, default=False)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    client = db.relationship("Client", backref=db.backref("wa_chat_session", uselist=False))

    @property
    def state_data(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_data_json or "{}")
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @state_data.setter
    def state_data(self, value: dict[str, Any] | None) -> None:
        self.state_data_json = json.dumps(value or {}, ensure_ascii=False)

    def touch(self) -> None:
        self.last_message_at = datetime.utcnow()
