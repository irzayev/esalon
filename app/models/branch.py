from datetime import datetime
from ..extensions import db


class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    phone = db.Column(db.String(40))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
