from datetime import datetime

from ..extensions import db
from .client import BODY_TYPE_LABELS, CarBodyType


def matches_car_body_type(entity_body_type: str | None, car_body_type: str | None) -> bool:
    """True if service/package can be offered for this car body type."""
    if not car_body_type:
        return True
    return (entity_body_type or CarBodyType.SEDAN) == car_body_type


def body_type_label(body_type: str | None) -> str:
    from ..utils.i18n import translate

    if not body_type:
        body_type = CarBodyType.SEDAN
    key = f"car.body.{body_type}"
    label = translate(key)
    if label != key:
        return label
    return BODY_TYPE_LABELS.get(body_type, body_type)


class ServiceCategory(db.Model):
    __tablename__ = "service_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    icon = db.Column(db.String(40))  # tabler icon name (optional)
    sort_order = db.Column(db.Integer, default=0)

    services = db.relationship("Service", back_populates="category")


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("service_categories.id"))
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False, default=0)
    duration_min = db.Column(db.Integer, default=30)
    required_bay_type = db.Column(db.String(20))  # wash|dry_clean|polish|ppf|null
    body_type = db.Column(db.String(20), default=CarBodyType.SEDAN, nullable=False)
    bonus_eligible = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("ServiceCategory", back_populates="services")

    @property
    def body_type_label(self) -> str:
        return body_type_label(self.body_type)
    materials = db.relationship(
        "ServiceMaterial", back_populates="service", cascade="all, delete-orphan"
    )


class ServiceMaterial(db.Model):
    """Recipe — how much of each inventory item is consumed per service."""
    __tablename__ = "service_materials"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False)
    qty = db.Column(db.Float, default=0)

    service = db.relationship("Service", back_populates="materials")
    item = db.relationship("InventoryItem")


package_services = db.Table(
    "package_services",
    db.Column("package_id", db.Integer, db.ForeignKey("service_packages.id"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id"), primary_key=True),
)


class ServicePackage(db.Model):
    __tablename__ = "service_packages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False, default=0)
    body_type = db.Column(db.String(20), default=CarBodyType.SEDAN, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    services = db.relationship("Service", secondary=package_services)

    @property
    def body_type_label(self) -> str:
        return body_type_label(self.body_type)
