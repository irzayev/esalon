from datetime import datetime
from enum import StrEnum

from ..extensions import db


class CabinetType(StrEnum):
    HAIR = "hair"
    BARBER = "barber"
    NAILS = "nails"
    COSMETOLOGY = "cosmetology"
    MAKEUP = "makeup"
    MASSAGE = "massage"


CABINET_TYPE_LABELS = {
    CabinetType.HAIR: "Парикмахерский",
    CabinetType.BARBER: "Барбершоп",
    CabinetType.NAILS: "Маникюр / педикюр",
    CabinetType.COSMETOLOGY: "Косметология",
    CabinetType.MAKEUP: "Визаж",
    CabinetType.MASSAGE: "Массаж / SPA",
}


class Cabinet(db.Model):
    __tablename__ = "cabinets"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship("Branch", back_populates="cabinets")
    capabilities = db.relationship(
        "CabinetCapability",
        back_populates="cabinet",
        cascade="all, delete-orphan",
    )
    orders = db.relationship("Order", back_populates="cabinet")

    @property
    def capability_types(self) -> set[str]:
        return {c.cabinet_type for c in self.capabilities}

    @property
    def capability_labels(self) -> str:
        labels = []
        for t in sorted(self.capability_types):
            try:
                labels.append(CABINET_TYPE_LABELS[CabinetType(t)])
            except ValueError:
                labels.append(t)
        return ", ".join(labels) if labels else "—"

    def supports_types(self, required: set[str]) -> bool:
        if not required:
            return True
        return required.issubset(self.capability_types)


class CabinetCapability(db.Model):
    __tablename__ = "cabinet_capabilities"
    __table_args__ = (
        db.UniqueConstraint("cabinet_id", "cabinet_type", name="uq_cabinet_capability"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(
        db.Integer, db.ForeignKey("cabinets.id", ondelete="CASCADE"), nullable=False
    )
    cabinet_type = db.Column(db.String(20), nullable=False)

    cabinet = db.relationship("Cabinet", back_populates="capabilities")
