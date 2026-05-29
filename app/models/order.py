from datetime import datetime
from enum import StrEnum
from ..extensions import db


class OrderStatus(StrEnum):
    NEW = "new"
    BOOKED = "booked"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    DONE = "done"
    DELIVERED = "delivered"
    CANCELED = "canceled"


# Client is on-site / has been served (CRM «последнее посещение»).
VISIT_STATUSES = (
    OrderStatus.IN_PROGRESS,
    OrderStatus.DONE,
    OrderStatus.DELIVERED,
)


def order_visit_at(order: "Order") -> datetime | None:
    if order.status not in VISIT_STATUSES:
        return None
    return order.completed_at or order.started_at or order.created_at


STATUS_LABELS = {
    OrderStatus.NEW: ("Новый", "bg-slate-100 text-slate-700"),
    OrderStatus.BOOKED: ("Записан", "bg-blue-50 text-blue-600"),
    OrderStatus.IN_PROGRESS: ("В работе", "bg-amber-50 text-amber-700"),
    OrderStatus.WAITING: ("Ожидание", "bg-purple-50 text-purple-600"),
    OrderStatus.DONE: ("Завершён", "bg-emerald-50 text-emerald-700"),
    OrderStatus.DELIVERED: ("Выдан", "bg-slate-900 text-white"),
    OrderStatus.CANCELED: ("Отменён", "bg-rose-50 text-rose-700"),
}


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    status = db.Column(db.String(20), default=OrderStatus.NEW, nullable=False, index=True)

    subtotal = db.Column(db.Float, default=0)
    discount_type = db.Column(db.String(20))  # fixed|percent|manual
    discount_value = db.Column(db.Float, default=0)
    discount_reason = db.Column(db.String(255))
    bonus_used = db.Column(db.Float, default=0)
    vat_amount = db.Column(db.Float, default=0)
    final_total = db.Column(db.Float, default=0)

    notes = db.Column(db.Text)
    bay_id = db.Column(db.Integer, db.ForeignKey("bays.id"), index=True)
    scheduled_at = db.Column(db.DateTime)
    scheduled_end_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    inventory_consumed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    branch = db.relationship("Branch")
    bay = db.relationship("Bay", back_populates="orders")
    client = db.relationship("Client", back_populates="orders")
    material_plans = db.relationship(
        "OrderMaterialPlan", back_populates="order", cascade="all, delete-orphan"
    )
    car = db.relationship("Car", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    photos = db.relationship("OrderPhoto", back_populates="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="order", cascade="all, delete-orphan")
    assignee = db.relationship("Employee", foreign_keys=[assigned_to_id])
    assignments = db.relationship(
        "OrderAssignment",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderAssignment.assigned_at",
    )

    @property
    def assignee_names(self) -> str:
        from ..services.order_assignees import assignee_names
        return assignee_names(self)

    @property
    def assignees(self) -> list:
        from ..services.order_assignees import get_assignees
        return get_assignees(self)

    @property
    def status_label(self) -> tuple[str, str]:
        from ..utils.i18n import order_status_label
        try:
            return order_status_label(self.status)
        except ValueError:
            return self.status, "bg-slate-100"

    @property
    def paid_total(self) -> float:
        from .payment import PaymentStatus
        return sum(p.amount for p in self.payments if p.status == PaymentStatus.SUCCESS)

    @property
    def is_paid(self) -> bool:
        return self.paid_total >= (self.final_total or 0) - 0.01


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"))
    package_id = db.Column(db.Integer, db.ForeignKey("service_packages.id"))
    name = db.Column(db.String(200), nullable=False)
    qty = db.Column(db.Float, default=1)
    price = db.Column(db.Float, default=0)

    order = db.relationship("Order", back_populates="items")
    service = db.relationship("Service")
    package = db.relationship("ServicePackage")

    @property
    def total(self) -> float:
        return (self.qty or 0) * (self.price or 0)


class OrderPhoto(db.Model):
    __tablename__ = "order_photos"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    kind = db.Column(db.String(20), default="before")  # before|after|other
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", back_populates="photos")
