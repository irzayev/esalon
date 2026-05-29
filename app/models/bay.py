from datetime import datetime
from enum import StrEnum

from ..extensions import db


class BayType(StrEnum):
    WASH = "wash"
    DRY_CLEAN = "dry_clean"
    POLISH = "polish"
    PPF = "ppf"


BAY_TYPE_LABELS = {
    BayType.WASH: "Мойка",
    BayType.DRY_CLEAN: "Химчистка",
    BayType.POLISH: "Полировка",
    BayType.PPF: "PPF",
}


class Bay(db.Model):
    __tablename__ = "bays"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship("Branch", back_populates="bays")
    capabilities = db.relationship(
        "BayCapability",
        back_populates="bay",
        cascade="all, delete-orphan",
    )
    orders = db.relationship("Order", back_populates="bay")

    @property
    def capability_types(self) -> set[str]:
        return {c.bay_type for c in self.capabilities}

    @property
    def capability_labels(self) -> str:
        labels = []
        for t in sorted(self.capability_types):
            try:
                labels.append(BAY_TYPE_LABELS[BayType(t)])
            except ValueError:
                labels.append(t)
        return ", ".join(labels) if labels else "—"

    def supports_types(self, required: set[str]) -> bool:
        if not required:
            return True
        return required.issubset(self.capability_types)


class BayCapability(db.Model):
    __tablename__ = "bay_capabilities"
    __table_args__ = (db.UniqueConstraint("bay_id", "bay_type", name="uq_bay_capability"),)

    id = db.Column(db.Integer, primary_key=True)
    bay_id = db.Column(db.Integer, db.ForeignKey("bays.id", ondelete="CASCADE"), nullable=False)
    bay_type = db.Column(db.String(20), nullable=False)

    bay = db.relationship("Bay", back_populates="capabilities")
