from datetime import datetime
from enum import StrEnum

from ..extensions import db
from .order import VISIT_STATUSES, order_visit_at


class ClientLevel(StrEnum):
    REGULAR = "regular"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # for client portal
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(20), unique=True, index=True)
    email = db.Column(db.String(160))  # deprecated, not used in UI
    birthday = db.Column(db.Date)
    level = db.Column(db.String(20), default=ClientLevel.REGULAR)
    notes = db.Column(db.Text)
    wa_last_reminder_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    orders = db.relationship("Order", back_populates="client")
    user = db.relationship("User", backref=db.backref("client_profile", uselist=False))

    @property
    def total_orders(self) -> int:
        return len(self.orders)

    @property
    def avg_check(self) -> float:
        if not self.orders:
            return 0.0
        return sum(o.final_total or 0 for o in self.orders) / len(self.orders)

    @property
    def last_visit_at(self) -> datetime | None:
        visits = [t for o in self.orders if (t := order_visit_at(o))]
        return max(visits) if visits else None
