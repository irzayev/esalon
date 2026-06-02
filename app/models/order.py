from datetime import datetime
from enum import StrEnum

from sqlalchemy import event

from ..extensions import db


class OrderStatus(StrEnum):
    NEW = "new"
    BOOKED = "booked"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    DONE = "done"
    DELIVERED = "delivered"
    CANCELED = "canceled"


# UI: filter pills, status dropdown (workflow order)
ORDER_STATUS_DISPLAY_ORDER: tuple[OrderStatus, ...] = (
    OrderStatus.NEW,
    OrderStatus.BOOKED,
    OrderStatus.WAITING,
    OrderStatus.IN_PROGRESS,
    OrderStatus.DONE,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELED,
)


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
    discount_type = db.Column(db.String(20))  # fixed|percent (legacy: manual → percent)
    discount_value = db.Column(db.Float, default=0)
    discount_reason = db.Column(db.String(255))
    promo_code_id = db.Column(db.Integer, db.ForeignKey("promo_codes.id"))
    promo_code_text = db.Column(db.String(8))
    promo_discount_type = db.Column(db.String(20))  # fixed|percent snapshot
    promo_discount_value = db.Column(db.Float, default=0)
    promo_use_counted = db.Column(db.Boolean, default=False)
    bonus_used = db.Column(db.Float, default=0)
    vat_amount = db.Column(db.Float, default=0)
    final_total = db.Column(db.Float, default=0)

    notes = db.Column(db.Text)
    bay_id = db.Column(db.Integer, db.ForeignKey("bays.id"), index=True)
    scheduled_at = db.Column(db.DateTime)
    scheduled_end_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    in_progress_minutes = db.Column(db.Integer, default=0)
    in_progress_since = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    inventory_consumed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    promo_code = db.relationship("PromoCode", back_populates="orders")
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
            from ..i18n.order_status_styles import DEFAULT_ORDER_STATUS_CLASS

            return self.status, DEFAULT_ORDER_STATUS_CLASS

    @property
    def work_minutes(self) -> int | None:
        from ..services.order_work_time import order_work_minutes

        return order_work_minutes(self)

    @property
    def order_subtotal(self) -> float:
        if self.subtotal:
            return float(self.subtotal)
        return sum((i.qty or 0) * (i.price or 0) for i in self.items)

    @property
    def discount_amount(self) -> float:
        return calc_order_discount(
            self.order_subtotal, self.discount_type, self.discount_value
        )

    @property
    def promo_discount_amount(self) -> float:
        amount = calc_order_discount(
            self.order_subtotal,
            self.promo_discount_type_effective,
            self.promo_discount_value_effective,
        )
        return min(max(amount, 0.0), max(self.order_subtotal, 0.0))

    @property
    def promo_discount_type_effective(self) -> str | None:
        if self.promo_discount_type in ("fixed", "percent"):
            return self.promo_discount_type
        if self.promo_code and self.promo_code.discount_type in ("fixed", "percent"):
            return self.promo_code.discount_type
        return None

    @property
    def promo_discount_value_effective(self) -> float:
        if self.promo_discount_value and self.promo_discount_value > 0:
            return float(self.promo_discount_value)
        if self.promo_code and self.promo_code.discount_value:
            return float(self.promo_code.discount_value)
        return 0.0

    @property
    def paid_total(self) -> float:
        from .payment import PaymentStatus
        return sum(p.amount for p in self.payments if p.status == PaymentStatus.SUCCESS)

    @property
    def is_paid(self) -> bool:
        return self.paid_total >= (self.final_total or 0) - 0.01

    @property
    def amount_due(self) -> float:
        return max(0.0, round((self.final_total or 0) - self.paid_total, 2))


def calc_order_discount(
    subtotal: float,
    discount_type: str | None,
    discount_value: float | None,
) -> float:
    if not discount_type or not discount_value:
        return 0.0
    if discount_type == "fixed":
        return float(discount_value)
    if discount_type in ("percent", "manual"):
        return subtotal * float(discount_value) / 100
    return 0.0


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


@event.listens_for(Order, "before_update")
def _order_set_updated_at(_mapper, _connection, target: Order) -> None:
    target.updated_at = datetime.utcnow()
