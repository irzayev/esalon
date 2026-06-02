from datetime import datetime

from ..extensions import db


class PromoCode(db.Model):
    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False, index=True)
    discount_type = db.Column(db.String(20), nullable=False)  # fixed|percent
    discount_value = db.Column(db.Float, default=0, nullable=False)
    valid_from = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
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

    def _now_utc(self) -> datetime:
        return datetime.utcnow()

    def is_not_yet_active(self, now: datetime | None = None) -> bool:
        if not self.valid_from:
            return False
        return (now or self._now_utc()) < self.valid_from

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.valid_until:
            return False
        return (now or self._now_utc()) > self.valid_until

    def is_usable(self, now: datetime | None = None) -> bool:
        if not self.is_active:
            return False
        if self.is_not_yet_active(now):
            return False
        if self.is_expired(now):
            return False
        if not self.is_unlimited and (self.used_count or 0) >= self.max_uses:
            return False
        return True
