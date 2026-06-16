"""Destructive reset of operational data: orders, payments, consumption, payroll."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..extensions import db
from ..models.order import Order, OrderItem, OrderPhoto
from ..models.order_item_plan import OrderItemPlan
from ..models.payment import Payment
from ..models.azericard import AzericardLog, AzericardPaymentIntent
from ..models.inventory import InventoryItem, InventoryMovement
from ..models.bonus import BonusWallet, BonusTransaction
from ..models.employee import Salary
from ..models.cash_expense import CashExpense
from ..models.audit import AuditLog


def reset_operational_data(upload_folder: str | Path) -> dict[str, int]:
    """
    Clears orders, revenue (payments), item consumption history, bonuses and payroll.
    Keeps clients, catalog (services, inventory items), employees and users.
    Stock quantities are rolled back to the state before all warehouse movements.
    """
    upload_base = Path(upload_folder)
    stats: dict[str, int] = {}

    movements = InventoryMovement.query.all()
    for m in movements:
        item = db.session.get(InventoryItem, m.item_id)
        if item is not None:
            item.qty = round((item.qty or 0) - float(m.delta), 4)
    stats["movements"] = len(movements)
    InventoryMovement.query.delete(synchronize_session=False)

    stats["bonus_transactions"] = BonusTransaction.query.delete(synchronize_session=False)
    for wallet in BonusWallet.query.all():
        wallet.balance = 0.0
        wallet.lifetime_earned = 0.0
        wallet.lifetime_spent = 0.0

    stats["salaries"] = Salary.query.delete(synchronize_session=False)
    stats["cash_expenses"] = CashExpense.query.delete(synchronize_session=False)

    photos = OrderPhoto.query.all()
    stats["photos"] = len(photos)
    for photo in photos:
        fp = upload_base / photo.filename
        if fp.is_file():
            fp.unlink(missing_ok=True)
    orders_dir = upload_base / "orders"
    if orders_dir.is_dir():
        shutil.rmtree(orders_dir, ignore_errors=True)

    stats["azericard_logs"] = AzericardLog.query.delete(synchronize_session=False)
    stats["azericard_intents"] = AzericardPaymentIntent.query.delete(synchronize_session=False)
    stats["payments"] = Payment.query.delete(synchronize_session=False)
    stats["item_plans"] = OrderItemPlan.query.delete(synchronize_session=False)
    stats["order_items"] = OrderItem.query.delete(synchronize_session=False)
    OrderPhoto.query.delete(synchronize_session=False)
    stats["order_audit_logs"] = (
        AuditLog.query.filter(AuditLog.entity == "order").delete(synchronize_session=False)
    )
    stats["orders"] = Order.query.delete(synchronize_session=False)

    db.session.commit()
    return stats


def operational_data_counts() -> dict[str, int]:
    """Current row counts for the reset preview."""
    return {
        "orders": Order.query.count(),
        "payments": Payment.query.count(),
        "movements": InventoryMovement.query.count(),
        "consumption_movements": InventoryMovement.query.filter(InventoryMovement.delta < 0).count(),
        "bonus_transactions": BonusTransaction.query.count(),
        "salaries": Salary.query.count(),
        "cash_expenses": CashExpense.query.count(),
    }
