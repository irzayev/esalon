"""Compute and apply warehouse consumption for completed orders."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, update

from ..extensions import db
from ..models.order import Order, OrderItem
from ..models.order_material import OrderMaterialPlan
from ..models.inventory import InventoryItem, InventoryMovement
from ..models.service import Service, ServicePackage, ServiceMaterial


def compute_material_totals(order: Order) -> dict[int, float]:
    """Aggregate recipe quantities by inventory item for an order."""
    totals: dict[int, float] = defaultdict(float)
    for item in order.items:
        multiplier = float(item.qty or 1)
        if item.package_id:
            pkg = db.session.get(ServicePackage, item.package_id)
            if not pkg:
                continue
            for svc in pkg.services:
                _add_service_materials(totals, svc.id, multiplier)
        elif item.service_id:
            _add_service_materials(totals, item.service_id, multiplier)
    return dict(totals)


def _add_service_materials(totals: dict[int, float], service_id: int, multiplier: float) -> None:
    rows = ServiceMaterial.query.filter_by(service_id=service_id).all()
    for row in rows:
        totals[row.inventory_item_id] += float(row.qty or 0) * multiplier


def ensure_plans_from_movements(order: Order) -> None:
    """Align plan rows with warehouse movements (e.g. after reopening consume page)."""
    if not order.inventory_consumed_at:
        return
    applied = get_applied_quantities_from_movements(order)
    if not applied:
        return
    by_item = {p.inventory_item_id: p for p in order.material_plans}
    for item_id, qty in applied.items():
        plan = by_item.get(item_id)
        if plan:
            plan.qty_used = qty
        else:
            db.session.add(
                OrderMaterialPlan(
                    order_id=order.id,
                    inventory_item_id=item_id,
                    qty_planned=0,
                    qty_used=qty,
                    is_manual=True,
                )
            )
    db.session.commit()


def get_applied_quantities_from_movements(order: Order) -> dict[int, float]:
    """Net consumed per inventory item from warehouse movements for this order."""
    totals: dict[int, float] = defaultdict(float)
    for m in InventoryMovement.query.filter_by(order_id=order.id).all():
        totals[m.item_id] += -float(m.delta)
    return {k: round(v, 4) for k, v in totals.items() if v > 1e-9}


def order_has_material_lines(order: Order) -> bool:
    """True if recipes or draft plan rows require consumption."""
    if compute_material_totals(order):
        return True
    return any((p.qty_used or 0) > 0 for p in order.material_plans)


def sync_material_plan(
    order: Order,
    force: bool = False,
    *,
    planned_only: bool = False,
) -> list[OrderMaterialPlan]:
    """Create or refresh material plan from recipes. If planned_only, keep qty_used unchanged."""
    if order.inventory_consumed_at and not force and not planned_only:
        return _sorted_plans(order)

    if order.inventory_consumed_at and planned_only:
        totals = compute_material_totals(order)
        for plan in order.material_plans:
            if not plan.is_manual and plan.inventory_item_id in totals:
                plan.qty_planned = totals[plan.inventory_item_id]
        db.session.commit()
        return _sorted_plans(order)

    totals = compute_material_totals(order)

    for plan in list(order.material_plans):
        if plan.is_manual:
            continue
        if plan.inventory_item_id not in totals:
            db.session.delete(plan)

    by_item = {p.inventory_item_id: p for p in order.material_plans}
    plans: list[OrderMaterialPlan] = []

    for item_id, qty in totals.items():
        plan = by_item.get(item_id)
        if not plan:
            plan = OrderMaterialPlan(
                order_id=order.id,
                inventory_item_id=item_id,
                qty_planned=qty,
                qty_used=qty,
                is_manual=False,
            )
            db.session.add(plan)
        elif plan.is_manual:
            plan.qty_planned = qty
        else:
            plan.qty_planned = qty
            if force or not order.inventory_consumed_at:
                plan.qty_used = qty
        plans.append(plan)

    for plan in order.material_plans:
        if plan.is_manual and plan not in plans:
            plans.append(plan)

    db.session.commit()
    return _sorted_plans(order, plans)


def add_plan_line(order: Order, inventory_item_id: int, qty: float) -> tuple[bool, str]:
    inv = db.session.get(InventoryItem, inventory_item_id)
    if not inv:
        return False, "Материал не найден"
    if qty <= 0:
        return False, "Укажите количество больше нуля"

    plan = OrderMaterialPlan.query.filter_by(
        order_id=order.id, inventory_item_id=inventory_item_id
    ).first()
    if plan:
        plan.qty_used = qty
        plan.is_manual = True
    else:
        db.session.add(
            OrderMaterialPlan(
                order_id=order.id,
                inventory_item_id=inventory_item_id,
                qty_planned=0,
                qty_used=qty,
                is_manual=True,
            )
        )
    db.session.commit()
    if order.inventory_consumed_at:
        return True, f"Добавлено: {inv.name}. Нажмите «Применить изменения» для склада."
    return True, f"Добавлено: {inv.name}"


def remove_plan_line(order: Order, plan_id: int) -> tuple[bool, str]:
    plan = OrderMaterialPlan.query.filter_by(id=plan_id, order_id=order.id).first()
    if not plan:
        return False, "Строка не найдена"
    name = plan.item.name if plan.item else "материал"
    db.session.delete(plan)
    db.session.commit()
    if order.inventory_consumed_at:
        return True, f"Удалено: {name}. Нажмите «Применить изменения» для склада."
    return True, f"Удалено: {name}"


def save_plan_draft(order: Order, rows: list[tuple[int, float]]) -> tuple[bool, str]:
    updated = 0
    for plan_id, qty in rows:
        if not plan_id:
            continue
        plan = OrderMaterialPlan.query.filter_by(id=plan_id, order_id=order.id).first()
        if not plan:
            continue
        plan.qty_used = max(0.0, float(qty))
        updated += 1
    db.session.commit()
    if order.inventory_consumed_at:
        return True, (
            "Количества сохранены. Нажмите «Применить изменения» для обновления склада."
            if updated
            else "Нет изменений"
        )
    return True, "Количества сохранены" if updated else "Нет изменений"


def _sync_plans_from_quantities(order: Order, quantities: dict[int, float]) -> None:
    kept = {int(iid): float(qty) for iid, qty in quantities.items() if float(qty) > 1e-9}
    for plan in list(order.material_plans):
        qty = kept.get(plan.inventory_item_id, 0)
        if qty <= 0:
            db.session.delete(plan)
        else:
            plan.qty_used = qty

    db.session.flush()
    existing_ids = {p.inventory_item_id for p in order.material_plans}
    for item_id, qty in kept.items():
        if item_id in existing_ids:
            continue
        db.session.add(
            OrderMaterialPlan(
                order_id=order.id,
                inventory_item_id=item_id,
                qty_planned=qty,
                qty_used=qty,
                is_manual=True,
            )
        )


def apply_material_consumption(order: Order, quantities: dict[int, float]) -> tuple[bool, str]:
    """First-time deduct inventory and record movements."""
    if order.inventory_consumed_at:
        return apply_consumption_adjustment(order, quantities)

    if not quantities:
        return False, "Укажите материалы для списания"

    shortages: list[str] = []
    for item_id, qty in quantities.items():
        if qty <= 0:
            continue
        inv = db.session.get(InventoryItem, item_id)
        if not inv:
            continue
        if (inv.qty or 0) < qty - 1e-9:
            shortages.append(f"{inv.name}: нужно {qty:g} {inv.unit}, есть {inv.qty:g}")

    if shortages:
        return False, "Недостаточно на складе: " + "; ".join(shortages)

    for item_id, qty in quantities.items():
        if qty <= 0:
            continue
        inv = db.session.get(InventoryItem, item_id)
        if not inv:
            continue
        # Atomic conditional decrement guards against concurrent consumption
        # driving stock negative (check-then-act race).
        result = db.session.execute(
            update(InventoryItem)
            .where(InventoryItem.id == inv.id, InventoryItem.qty >= qty - 1e-9)
            .values(qty=func.round(InventoryItem.qty - qty, 4))
        )
        if result.rowcount == 0:
            db.session.rollback()
            db.session.refresh(inv)
            return False, (
                f"Недостаточно на складе: {inv.name} "
                f"(нужно {qty:g} {inv.unit}, есть {inv.qty:g})"
            )
        db.session.add(
            InventoryMovement(
                item_id=inv.id,
                delta=-qty,
                reason=f"Заказ #{order.number}",
                order_id=order.id,
            )
        )

    _sync_plans_from_quantities(order, quantities)
    order.inventory_consumed_at = datetime.utcnow()
    db.session.commit()
    return True, "Материалы списаны со склада"


def apply_consumption_adjustment(order: Order, quantities: dict[int, float]) -> tuple[bool, str]:
    """Adjust warehouse after consumption: apply delta vs current movements."""
    if not order.inventory_consumed_at:
        return apply_material_consumption(order, quantities)

    old = get_applied_quantities_from_movements(order)
    new = {int(k): float(v) for k, v in quantities.items() if float(v) > 1e-9}
    all_ids = set(old) | set(new)

    shortages: list[str] = []
    for item_id in all_ids:
        delta = new.get(item_id, 0) - old.get(item_id, 0)
        if delta <= 1e-9:
            continue
        inv = db.session.get(InventoryItem, item_id)
        if not inv:
            continue
        if (inv.qty or 0) < delta - 1e-9:
            shortages.append(f"{inv.name}: нужно ещё {delta:g} {inv.unit}, есть {inv.qty:g}")

    if shortages:
        return False, "Недостаточно на складе: " + "; ".join(shortages)

    changes = 0
    for item_id in all_ids:
        old_q = old.get(item_id, 0)
        new_q = new.get(item_id, 0)
        delta = round(new_q - old_q, 4)
        if abs(delta) < 1e-9:
            continue

        inv = db.session.get(InventoryItem, item_id)
        if not inv:
            continue
        inv.qty = round((inv.qty or 0) - delta, 4)
        db.session.add(
            InventoryMovement(
                item_id=inv.id,
                delta=-delta,
                reason=f"Корректировка заказа #{order.number}",
                order_id=order.id,
            )
        )
        changes += 1

    _sync_plans_from_quantities(order, new)

    if new:
        order.inventory_consumed_at = datetime.utcnow()
    else:
        order.inventory_consumed_at = None

    db.session.commit()
    if not changes and not new and not old:
        return True, "Изменений нет"
    if not new and old:
        return True, "Списание отменено, материалы возвращены на склад"
    return True, f"Склад обновлён ({changes} поз.)"


def _sorted_plans(order: Order, plans: list[OrderMaterialPlan] | None = None) -> list[OrderMaterialPlan]:
    items = plans if plans is not None else list(order.material_plans)
    return sorted(items, key=lambda p: (p.item.name if p.item else "", p.id))
