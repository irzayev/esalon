from datetime import datetime
from ..extensions import db


class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    phone = db.Column(db.String(40))
    work_open = db.Column(db.String(5), nullable=False, default="08:00")
    work_close = db.Column(db.String(5), nullable=False, default="20:00")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cabinets = db.relationship(
        "Cabinet",
        back_populates="branch",
        cascade="all, delete-orphan",
        order_by="Cabinet.sort_order",
    )
