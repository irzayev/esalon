from datetime import date, datetime

from ..extensions import db


class PromoCode(db.Model):
    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False, index=True)
    discount_type = db.Column(db.String(20), nullable=False)  # fixed|percent
    discount_value = db.Column(db.Float, default=0, nullable=False)
    valid_until = db.Column(db.Date)
    max_uses = db.Column(db.Integer, default=0)  # 0 = unlimited
    used_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    orders = db.relationship("Order", back_populates="promo_code")

    @property
    def is_unlimited(self) -> bool:
        return (self.max_uses or 0) <= 0

    @property
    def uses_remaining(self) -> int | None:
        if self.is_unlimited:
            return None
        return max(0, self.max_uses - (self.used_count or 0))

    def is_expired(self, on_date: date | None = None) -> bool:
        if not self.valid_until:
            return False
        check = on_date or date.today()
        return check > self.valid_until

    def is_usable(self) -> bool:
        if not self.is_active:
            return False
        if self.is_expired():
            return False
        if not self.is_unlimited and (self.used_count or 0) >= self.max_uses:
            return False
        return True
