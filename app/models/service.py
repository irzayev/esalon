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
    bonus_eligible = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("ServiceCategory", back_populates="services")
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
    is_active = db.Column(db.Boolean, default=True)
    services = db.relationship("Service", secondary=package_services)
