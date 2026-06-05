"""Rule-based chatbot responses (info keywords and menu triggers)."""
from datetime import datetime

from ..extensions import db


class ChatbotRule(db.Model):
    __tablename__ = "chatbot_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    rule_type = db.Column(db.String(20), nullable=False, default="info")  # info | menu
    triggers = db.Column(db.Text, nullable=False, default="")  # comma-separated keywords
    response_template = db.Column(db.Text, nullable=False, default="")
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def trigger_list(self) -> list[str]:
        return [t.strip().lower() for t in (self.triggers or "").split(",") if t.strip()]
