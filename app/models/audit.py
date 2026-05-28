from datetime import datetime
from ..extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(80), nullable=False)
    entity = db.Column(db.String(80))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User")
