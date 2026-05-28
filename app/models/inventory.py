from datetime import datetime
from ..extensions import db


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    sku = db.Column(db.String(40), index=True)
    unit = db.Column(db.String(20), default="шт")  # шт, ml, l, kg
    qty = db.Column(db.Float, default=0)
    min_qty = db.Column(db.Float, default=0)
    cost_price = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_low(self) -> bool:
        return (self.qty or 0) <= (self.min_qty or 0)


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
