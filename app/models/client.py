from datetime import datetime
from enum import StrEnum

from ..extensions import db
from .order import VISIT_STATUSES, order_visit_at


class ClientLevel(StrEnum):
    REGULAR = "regular"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class CarBodyType(StrEnum):
    SEDAN = "sedan"
    SUV = "suv"
    OFFROAD = "offroad"
    VAN = "van"


BODY_TYPE_LABELS: dict[str, str] = {
    CarBodyType.SEDAN: "Седан",
    CarBodyType.SUV: "SUV",
    CarBodyType.OFFROAD: "Внедорожник",
    CarBodyType.VAN: "VAN",
}


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

    cars = db.relationship("Car", back_populates="client", cascade="all, delete-orphan")
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


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    brand = db.Column(db.String(80))
    model = db.Column(db.String(80))
    body_type = db.Column(db.String(20), default=CarBodyType.SEDAN)
    plate = db.Column(db.String(12), index=True)
    year = db.Column(db.Integer)
    color = db.Column(db.String(40))
    vin = db.Column(db.String(40))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", back_populates="cars")
    orders = db.relationship("Order", back_populates="car")

    @property
    def body_type_label(self) -> str:
        from ..utils.i18n import translate
        key = f"car.body.{self.body_type}"
        label = translate(key)
        if label != key:
            return label
        return BODY_TYPE_LABELS.get(self.body_type, self.body_type or "—")

    @property
    def display(self) -> str:
        parts = [p for p in [self.brand, self.model, self.body_type_label] if p]
        title = " ".join(parts)
        return f"{title} · {self.plate}" if self.plate else title
