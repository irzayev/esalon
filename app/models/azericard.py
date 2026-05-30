"""Azericard payment intents and diagnostic logs."""
from datetime import datetime
from enum import StrEnum

from ..extensions import db


class AzericardIntentStatus(StrEnum):
    CREATED = "created"
    REDIRECTED = "redirected"
    FAILED = "failed"
    COMPLETED = "completed"


class AzericardPaymentIntent(db.Model):
    """One MPI session per Azericard ORDER id (unique on gateway)."""

    __tablename__ = "azericard_payment_intents"

    id = db.Column(db.Integer, primary_key=True)
    order = db.Column(db.String(20), nullable=False, unique=True, index=True)
    pay_token = db.Column(db.String(64), unique=True, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="944")
    status = db.Column(db.String(20), nullable=False, default=AzericardIntentStatus.CREATED)
    nonce = db.Column(db.String(64))
    terminal = db.Column(db.String(16))
    rc = db.Column(db.String(8))
    action = db.Column(db.String(4))
    approval = db.Column(db.String(12))
    rrn = db.Column(db.String(16))
    int_ref = db.Column(db.String(40))
    note = db.Column(db.String(255))
    audit_channel = db.Column(db.String(32))  # client_portal | staff
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payment = db.relationship("Payment", backref=db.backref("azericard_intent", uselist=False))
    business_order = db.relationship("Order", foreign_keys=[order_id])


class AzericardLog(db.Model):
    __tablename__ = "azericard_logs"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    direction = db.Column(db.String(8), nullable=False, default="out")  # out|in
    event = db.Column(db.String(48), nullable=False)
    order = db.Column(db.String(20), index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    business_order = db.relationship("Order", foreign_keys=[order_id])
    http_status = db.Column(db.Integer)
    rc = db.Column(db.String(8))
    note = db.Column(db.String(500))
    raw_body = db.Column(db.Text)
