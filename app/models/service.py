from datetime import datetime

from ..extensions import db
from .client import BODY_TYPE_LABELS, CarBodyType

_VALID_BODY_TYPES = {t.value for t in CarBodyType}


def parse_body_types(raw: str | None) -> set[str]:
    if not raw:
        return {CarBodyType.SEDAN}
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    filtered = parts & _VALID_BODY_TYPES
    return filtered or {CarBodyType.SEDAN}


def serialize_body_types(types: set[str] | list[str]) -> str:
    type_set = set(types) & _VALID_BODY_TYPES
    if not type_set:
        return CarBodyType.SEDAN
    return ",".join(t.value for t in CarBodyType if t.value in type_set)


def body_types_from_form(values: list[str]) -> set[str] | None:
    selected = {v for v in values if v in _VALID_BODY_TYPES}
    return selected or None


def matches_car_body_type(entity_body_types: str | None, car_body_type: str | None) -> bool:
    """True if service/package can be offered for this car body type."""
    if not car_body_type:
        return True
    return car_body_type in parse_body_types(entity_body_types)


def body_types_intersect(a: str | None, b: str | None) -> bool:
    return bool(parse_body_types(a) & parse_body_types(b))


def body_type_label(body_type: str | None) -> str:
    from ..utils.i18n import translate

    if not body_type:
        body_type = CarBodyType.SEDAN
    key = f"car.body.{body_type}"
    label = translate(key)
    if label != key:
        return label
    return BODY_TYPE_LABELS.get(body_type, body_type)


def body_types_label(raw: str | None) -> str:
    types = parse_body_types(raw)
    return ", ".join(body_type_label(t.value) for t in CarBodyType if t.value in types)


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
    body_types = db.Column(db.String(120), default=CarBodyType.SEDAN, nullable=False)
    bonus_eligible = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("ServiceCategory", back_populates="services")
    materials = db.relationship(
        "ServiceMaterial", back_populates="service", cascade="all, delete-orphan"
    )

    @property
    def body_types_set(self) -> set[str]:
        return parse_body_types(self.body_types)

    @property
    def body_type_label(self) -> str:
        return body_types_label(self.body_types)


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
    body_types = db.Column(db.String(120), default=CarBodyType.SEDAN, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    use_custom_duration = db.Column(db.Boolean, default=False, nullable=False)
    custom_duration_min = db.Column(db.Integer)
    services = db.relationship("Service", secondary=package_services)

    @property
    def body_types_set(self) -> set[str]:
        return parse_body_types(self.body_types)

    @property
    def body_type_label(self) -> str:
        return body_types_label(self.body_types)

    def computed_duration_min(self) -> int:
        """Sum of duration_min for all services in the package."""
        return sum(int(svc.duration_min or 30) for svc in self.services)

    @property
    def duration_min(self) -> int:
        if self.use_custom_duration and self.custom_duration_min:
            return int(self.custom_duration_min)
        return self.computed_duration_min()
