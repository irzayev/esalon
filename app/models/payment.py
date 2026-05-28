from datetime import datetime
from enum import StrEnum
from ..extensions import db


class PaymentMethod(StrEnum):
    CASH = "cash"
    POS = "pos"
    AZERICARD = "azericard"
    TRANSFER = "transfer"
    BONUS = "bonus"
    MIXED = "mixed"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


METHOD_LABELS = {
    PaymentMethod.CASH: "Наличные",
    PaymentMethod.POS: "POS терминал",
    PaymentMethod.AZERICARD: "Azericard",
    PaymentMethod.TRANSFER: "Перевод",
    PaymentMethod.BONUS: "Бонусы",
    PaymentMethod.MIXED: "Смешанная",
}


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    method = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default=PaymentStatus.PENDING, nullable=False)
    transaction_reference = db.Column(db.String(120))
    raw_response = db.Column(db.Text)  # for Azericard payloads
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", back_populates="payments")

    @property
    def method_label(self) -> str:
        try:
            return METHOD_LABELS[PaymentMethod(self.method)]
        except Exception:
            return self.method
