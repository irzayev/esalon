"""Client notes: individual timestamped notes per client, with optional photo."""
from datetime import datetime

from ..extensions import db


class ClientNote(db.Model):
    __tablename__ = "client_notes"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(255))  # relative path inside /static/uploads
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = db.relationship("Client", back_populates="client_notes")
