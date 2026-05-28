from datetime import datetime

from ..extensions import db


class CashExpense(db.Model):
    """Manual cash outflows recorded in the finance register."""

    __tablename__ = "cash_expenses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship("Branch", backref="cash_expenses")
