"""Пользовательские шаблоны WhatsApp для ручной рассылки."""
from datetime import datetime

from ..extensions import db


class WaMessageTemplate(db.Model):
    __tablename__ = "wa_message_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
