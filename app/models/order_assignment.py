"""Many-to-many: order ↔ employees (executors)."""
from datetime import datetime

from ..extensions import db


class OrderAssignment(db.Model):
    __tablename__ = "order_assignments"
    __table_args__ = (
        db.UniqueConstraint("order_id", "employee_id", name="uq_order_employee"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id = db.Column(
        db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", back_populates="assignments")
    employee = db.relationship("Employee", back_populates="order_assignments")
