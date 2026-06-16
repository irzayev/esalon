from datetime import datetime

from ..extensions import db


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
    required_cabinet_type = db.Column(db.String(20))  # hair|nails|cosmetology|…|null
    bonus_eligible = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    client_reservable = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("ServiceCategory", back_populates="services")
    items = db.relationship(
        "ServiceItem", back_populates="service", cascade="all, delete-orphan"
    )


class ServiceItem(db.Model):
    """Recipe — how much of each inventory item is consumed per service."""
    __tablename__ = "service_items"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False)
    qty = db.Column(db.Float, default=0)

    service = db.relationship("Service", back_populates="items")
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
    required_cabinet_type = db.Column(db.String(20))  # hair|nails|cosmetology|…|null
    is_active = db.Column(db.Boolean, default=True)
    client_reservable = db.Column(db.Boolean, default=True, nullable=False)
    use_custom_duration = db.Column(db.Boolean, default=False, nullable=False)
    custom_duration_min = db.Column(db.Integer)
    services = db.relationship("Service", secondary=package_services)

    def computed_duration_min(self) -> int:
        """Sum of duration_min for all services in the package."""
        return sum(int(svc.duration_min or 30) for svc in self.services)

    @property
    def duration_min(self) -> int:
        if self.use_custom_duration and self.custom_duration_min:
            return int(self.custom_duration_min)
        return self.computed_duration_min()

    def resolve_required_cabinet_types(self) -> set[str]:
        """Package override, else union of included services' required cabinet types."""
        if self.required_cabinet_type:
            return {self.required_cabinet_type}
        return {svc.required_cabinet_type for svc in self.services if svc.required_cabinet_type}
