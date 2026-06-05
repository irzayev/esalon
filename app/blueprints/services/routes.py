from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from sqlalchemy.orm import joinedload

from ...extensions import db
from ...models.service import (
    Service,
    ServiceCategory,
    ServicePackage,
    ServiceMaterial,
    matches_car_body_type,
    body_types_from_form,
    serialize_body_types,
    body_types_intersect,
)
from ...models.bay import BayType, BAY_TYPE_LABELS
from ...models.inventory import InventoryItem
from ...utils.decorators import manager_required, staff_required
from ...utils.i18n import get_body_type_choices
from ...utils.list_sort import parse_list_sort, make_toggle_sort_dir, sql_order

bp = Blueprint("services", __name__)

_SERVICE_SORT_KEYS = frozenset({"name", "category", "body_type", "duration", "price"})
_PACKAGE_SORT_KEYS = frozenset({"name", "body_type", "duration", "price"})


@bp.route("/")
@login_required
@staff_required
def index():
    cats = ServiceCategory.query.order_by(ServiceCategory.sort_order, ServiceCategory.name).all()

    sort, direction = parse_list_sort(
        request.args, _SERVICE_SORT_KEYS, "name", default_dir="asc"
    )
    pkg_sort, pkg_direction = parse_list_sort(
        request.args,
        _PACKAGE_SORT_KEYS,
        "name",
        default_dir="asc",
        sort_key="pkg_sort",
        dir_key="pkg_dir",
    )

    service_sort_map = {
        "name": Service.name,
        "category": ServiceCategory.name,
        "body_type": Service.body_types,
        "duration": Service.duration_min,
        "price": Service.price,
    }
    services = (
        Service.query.outerjoin(ServiceCategory, Service.category_id == ServiceCategory.id)
        .options(joinedload(Service.category), joinedload(Service.materials))
        .order_by(
            sql_order(service_sort_map[sort], direction, nullable=sort == "category"),
            Service.name.asc(),
        )
        .all()
    )

    package_sort_map = {
        "name": ServicePackage.name,
        "body_type": ServicePackage.body_types,
        "price": ServicePackage.price,
    }
    packages_q = ServicePackage.query.options(joinedload(ServicePackage.services))
    if pkg_sort == "duration":
        packages = packages_q.all()
        reverse = pkg_direction == "desc"
        packages.sort(
            key=lambda p: (p.duration_min, (p.name or "").lower()),
            reverse=reverse,
        )
    else:
        packages = (
            packages_q.order_by(
                sql_order(package_sort_map[pkg_sort], pkg_direction),
                ServicePackage.name.asc(),
            )
            .all()
        )

    list_query = {
        "sort": sort,
        "dir": direction,
        "pkg_sort": pkg_sort,
        "pkg_dir": pkg_direction,
    }

    return render_template(
        "services/index.html",
        cats=cats,
        services=services,
        packages=packages,
        sort=sort,
        sort_direction=direction,
        toggle_sort_dir=make_toggle_sort_dir(sort, direction),
        pkg_sort=pkg_sort,
        pkg_sort_direction=pkg_direction,
        toggle_pkg_sort_dir=make_toggle_sort_dir(pkg_sort, pkg_direction),
        list_query=list_query,
    )


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
        if _save_service(s):
            return redirect(url_for("services.service_edit", sid=s.id))
        cats = ServiceCategory.query.order_by(ServiceCategory.name).all()
        inventory = InventoryItem.query.order_by(InventoryItem.name).all()
        return render_template(
            "services/form.html",
            service=s,
            cats=cats,
            inventory=inventory,
            materials=[],
            bay_types=BayType,
            bay_type_labels=BAY_TYPE_LABELS,
            body_types=get_body_type_choices(),
        )
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
        body_types=get_body_type_choices(),
    )


@bp.route("/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def service_edit(sid: int):
    s = db.session.get(Service, sid) or abort(404)
    if request.method == "POST":
        if _save_service(s):
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
            body_types=get_body_type_choices(),
        )
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
        body_types=get_body_type_choices(),
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
        if _save_package(pkg):
            return redirect(url_for("services.index"))
        services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
        selected = {int(x) for x in request.form.getlist("service_ids") if x}
        return render_template(
            "services/package_form.html",
            package=pkg,
            services=services,
            selected=selected,
            body_types=get_body_type_choices(),
            bay_types=BayType,
            bay_type_labels=BAY_TYPE_LABELS,
        )
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template(
        "services/package_form.html",
        package=None,
        services=services,
        selected=set(),
        body_types=get_body_type_choices(),
        bay_types=BayType,
        bay_type_labels=BAY_TYPE_LABELS,
    )


@bp.route("/packages/<int:pid>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def package_edit(pid: int):
    pkg = db.session.get(ServicePackage, pid) or abort(404)
    if request.method == "POST":
        if _save_package(pkg):
            return redirect(url_for("services.index"))
        services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
        selected = {int(x) for x in request.form.getlist("service_ids") if x}
        return render_template(
            "services/package_form.html",
            package=pkg,
            services=services,
            selected=selected,
            body_types=get_body_type_choices(),
            bay_types=BayType,
            bay_type_labels=BAY_TYPE_LABELS,
        )
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    selected = {s.id for s in pkg.services}
    return render_template(
        "services/package_form.html",
        package=pkg,
        services=services,
        selected=selected,
        body_types=get_body_type_choices(),
        bay_types=BayType,
        bay_type_labels=BAY_TYPE_LABELS,
    )


@bp.post("/packages/<int:pid>/delete")
@login_required
@manager_required
def package_delete(pid: int):
    pkg = db.session.get(ServicePackage, pid) or abort(404)
    db.session.delete(pkg)
    db.session.commit()
    flash("Пакет удалён", "success")
    return redirect(url_for("services.index"))


def _save_service(s: Service) -> bool:
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
    s.client_reservable = bool(f.get("client_reservable"))
    selected = body_types_from_form(request.form.getlist("body_types"))
    if not selected:
        flash("Выберите хотя бы один тип автомобиля", "error")
        return False
    s.body_types = serialize_body_types(selected)
    if not s.id:
        db.session.add(s)
    db.session.commit()
    flash("Услуга сохранена", "success")
    return True


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


def _save_package(pkg: ServicePackage) -> bool:
    f = request.form
    pkg.name = f.get("name", "").strip()
    pkg.description = f.get("description", "")
    pkg.price = float(f.get("price") or 0)
    pkg.is_active = bool(f.get("is_active"))
    pkg.client_reservable = bool(f.get("client_reservable"))
    selected_types = body_types_from_form(request.form.getlist("body_types"))
    if not selected_types:
        flash("Выберите хотя бы один тип автомобиля", "error")
        return False
    pkg.body_types = serialize_body_types(selected_types)
    rbt = (f.get("required_bay_type") or "").strip() or None
    valid_bay_types = {t.value for t in BayType}
    pkg.required_bay_type = rbt if rbt in valid_bay_types else None
    service_ids = [int(x) for x in request.form.getlist("service_ids") if x]
    selected = Service.query.filter(Service.id.in_(service_ids)).all() if service_ids else []
    mismatched = [s.name for s in selected if not body_types_intersect(s.body_types, pkg.body_types)]
    if mismatched:
        flash(
            f"Услуги не подходят по типу кузова: {', '.join(mismatched)}",
            "error",
        )
        return False
    pkg.services = selected
    pkg.use_custom_duration = bool(f.get("use_custom_duration"))
    if pkg.use_custom_duration:
        try:
            mins = int(f.get("custom_duration_min") or 0)
        except (TypeError, ValueError):
            mins = 0
        if mins < 15:
            flash("Укажите длительность пакета не менее 15 минут", "error")
            return False
        pkg.custom_duration_min = mins
    else:
        pkg.custom_duration_min = None
    if not pkg.id:
        db.session.add(pkg)
    db.session.commit()
    flash("Пакет сохранён", "success")
    return True
