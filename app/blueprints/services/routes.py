from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required

from ...extensions import db
from ...models.service import Service, ServiceCategory, ServicePackage, ServiceMaterial
from ...models.bay import BayType, BAY_TYPE_LABELS
from ...models.inventory import InventoryItem
from ...utils.decorators import manager_required, staff_required

bp = Blueprint("services", __name__)


@bp.route("/")
@login_required
@staff_required
def index():
    cats = ServiceCategory.query.order_by(ServiceCategory.sort_order, ServiceCategory.name).all()
    services = Service.query.order_by(Service.name).all()
    packages = ServicePackage.query.order_by(ServicePackage.name).all()
    return render_template("services/index.html", cats=cats, services=services, packages=packages)


@bp.route("/categories/new", methods=["POST"])
@login_required
@manager_required
def category_new():
    name = request.form.get("name", "").strip()
    if name:
        db.session.add(ServiceCategory(name=name))
        db.session.commit()
        flash("Категория добавлена", "success")
    return redirect(url_for("services.index"))


@bp.post("/categories/<int:cid>/delete")
@login_required
@manager_required
def category_delete(cid: int):
    c = db.session.get(ServiceCategory, cid) or abort(404)
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for("services.index"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
@manager_required
def service_new():
    if request.method == "POST":
        s = Service()
        _save_service(s)
        _save_service_materials(s)
        return redirect(url_for("services.service_edit", sid=s.id))
    cats = ServiceCategory.query.order_by(ServiceCategory.name).all()
    inventory = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template(
        "services/form.html",
        service=None,
        cats=cats,
        inventory=inventory,
        materials=[],
        bay_types=BayType,
        bay_type_labels=BAY_TYPE_LABELS,
    )


@bp.route("/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def service_edit(sid: int):
    s = db.session.get(Service, sid) or abort(404)
    if request.method == "POST":
        _save_service(s)
        _save_service_materials(s)
        return redirect(url_for("services.service_edit", sid=s.id))
    cats = ServiceCategory.query.order_by(ServiceCategory.name).all()
    inventory = InventoryItem.query.order_by(InventoryItem.name).all()
    materials = ServiceMaterial.query.filter_by(service_id=s.id).all()
    return render_template(
        "services/form.html",
        service=s,
        cats=cats,
        inventory=inventory,
        materials=materials,
        bay_types=BayType,
        bay_type_labels=BAY_TYPE_LABELS,
    )


@bp.post("/<int:sid>/delete")
@login_required
@manager_required
def service_delete(sid: int):
    s = db.session.get(Service, sid) or abort(404)
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for("services.index"))


# ---- Packages ---- #

@bp.route("/packages/new", methods=["GET", "POST"])
@login_required
@manager_required
def package_new():
    if request.method == "POST":
        pkg = ServicePackage()
        _save_package(pkg)
        return redirect(url_for("services.index"))
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template("services/package_form.html", package=None, services=services, selected=set())


@bp.route("/packages/<int:pid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def package_edit(pid: int):
    pkg = db.session.get(ServicePackage, pid) or abort(404)
    if request.method == "POST":
        _save_package(pkg)
        return redirect(url_for("services.index"))
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    selected = {s.id for s in pkg.services}
    return render_template("services/package_form.html", package=pkg, services=services, selected=selected)


@bp.post("/packages/<int:pid>/delete")
@login_required
@manager_required
def package_delete(pid: int):
    pkg = db.session.get(ServicePackage, pid) or abort(404)
    db.session.delete(pkg)
    db.session.commit()
    flash("Пакет удалён", "success")
    return redirect(url_for("services.index"))


def _save_service(s: Service):
    f = request.form
    s.name = f.get("name", "").strip()
    s.description = f.get("description", "")
    s.price = float(f.get("price") or 0)
    s.duration_min = int(f.get("duration_min") or 30)
    rbt = (f.get("required_bay_type") or "").strip() or None
    valid_types = {t.value for t in BayType}
    s.required_bay_type = rbt if rbt in valid_types else None
    cat = f.get("category_id")
    s.category_id = int(cat) if cat else None
    s.bonus_eligible = bool(f.get("bonus_eligible"))
    s.is_active = bool(f.get("is_active"))
    if not s.id:
        db.session.add(s)
    db.session.commit()
    flash("Услуга сохранена", "success")


def _save_service_materials(service: Service) -> None:
    """Replace recipe lines from form arrays item_id[] and material_qty[]."""
    ServiceMaterial.query.filter_by(service_id=service.id).delete()
    item_ids = request.form.getlist("material_item_id")
    qtys = request.form.getlist("material_qty")
    for iid, qty in zip(item_ids, qtys):
        if not iid:
            continue
        q = float(qty or 0)
        if q <= 0:
            continue
        db.session.add(
            ServiceMaterial(service_id=service.id, inventory_item_id=int(iid), qty=q)
        )
    db.session.commit()


def _save_package(pkg: ServicePackage):
    f = request.form
    pkg.name = f.get("name", "").strip()
    pkg.description = f.get("description", "")
    pkg.price = float(f.get("price") or 0)
    pkg.is_active = bool(f.get("is_active"))
    service_ids = [int(x) for x in request.form.getlist("service_ids") if x]
    pkg.services = Service.query.filter(Service.id.in_(service_ids)).all() if service_ids else []
    if not pkg.id:
        db.session.add(pkg)
    db.session.commit()
    flash("Пакет сохранён", "success")
