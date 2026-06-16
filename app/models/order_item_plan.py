"""Planned/actual inventory item usage per order before warehouse deduction."""
from datetime import datetime
from ..extensions import db


class OrderItemPlan(db.Model):
    __tablename__ = "order_item_plans"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False)
    qty_planned = db.Column(db.Float, default=0)
    qty_used = db.Column(db.Float, default=0)
    is_manual = db.Column(db.Boolean, default=False, nullable=False)

    order = db.relationship("Order", back_populates="item_plans")
    item = db.relationship("InventoryItem")
