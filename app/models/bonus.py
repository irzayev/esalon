from datetime import datetime
from enum import StrEnum
from ..extensions import db


class BonusType(StrEnum):
    EARN = "earn"
    SPEND = "spend"
    EXPIRE = "expire"
    ADJUST = "adjust"


class BonusWallet(db.Model):
    __tablename__ = "bonus_wallets"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0)
    lifetime_earned = db.Column(db.Float, default=0)
    lifetime_spent = db.Column(db.Float, default=0)

    client = db.relationship("Client", backref=db.backref("wallet", uselist=False))


class BonusTransaction(db.Model):
    __tablename__ = "bonus_transactions"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    source_order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    comment = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
