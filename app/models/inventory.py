from datetime import date, datetime
from ..extensions import db

INVENTORY_UNITS = ("ml", "l", "mg", "kg", "sm", "m", "ed")
DEFAULT_INVENTORY_UNIT = "ed"


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    sku = db.Column(db.String(40), index=True)
    unit = db.Column(db.String(20), default=DEFAULT_INVENTORY_UNIT)
    qty = db.Column(db.Float, default=0)
    min_qty = db.Column(db.Float, default=0)
    cost_price = db.Column(db.Float, default=0)
    expires_at = db.Column(db.Date)
    purchased_at = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_low(self) -> bool:
        return (self.qty or 0) <= (self.min_qty or 0)

    @property
    def days_until_expiry(self) -> int | None:
        if not self.expires_at:
            return None
        return (self.expires_at - date.today()).days

    @property
    def is_expires_today(self) -> bool:
        if not self.expires_at:
            return False
        return self.expires_at == date.today()

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return self.expires_at < date.today()

    @property
    def is_expiring_soon(self) -> bool:
        days = self.days_until_expiry
        if days is None:
            return False
        return 0 < days <= 60

    @property
    def expiry_highlight(self) -> str | None:
        """critical = today or past, warning = 1–60 days left."""
        if not self.expires_at:
            return None
        if self.expires_at <= date.today():
            return "critical"
        if self.is_expiring_soon:
            return "warning"
        return None


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False)
    delta = db.Column(db.Float, nullable=False)  # +receive, -consume
    reason = db.Column(db.String(120))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship("InventoryItem")
    order = db.relationship("Order", backref="inventory_movements")
