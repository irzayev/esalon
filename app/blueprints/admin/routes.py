"""Admin blueprint: settings, integrations, users, backup."""
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, send_file, abort, current_app, jsonify
)
from flask_login import login_required, current_user
from io import BytesIO

from sqlalchemy import func

from ...extensions import db
from ...models.order import Order
from ...models.settings import Settings
from ...models.user import User, Role
from ...models.branch import Branch
from ...models.bay import Bay, BayCapability, BayType, BAY_TYPE_LABELS
from ...models.audit import AuditLog
from ...models.wa_template import WaMessageTemplate
from ...models.promo_code import PromoCode
from ...services.promo_code import generate_promo_code, normalize_promo_code
from ...utils.audit import log_audit
from ...utils.decorators import admin_required

_VALID_ROLES = {r.value for r in Role}


def _valid_role(raw: str | None, default: str = Role.WORKER) -> str:
    """Coerce a submitted role to a known enum value (defends against
    arbitrary role strings that would bypass role decorators)."""
    value = (raw or "").strip()
    return value if value in _VALID_ROLES else default
from ...utils.uploads import save_upload, ALLOWED_IMAGE
from ...services.backup import create_backup_zip, restore_backup_zip
from ...services.evolution_api import EvolutionAPIService
from ...services.branding import (
    DEFAULT_WA_READY,
    DEFAULT_WA_BOOKING,
    DEFAULT_WA_REMINDER,
    DEFAULT_WA_PAYMENT,
    DEFAULT_WA_STATUS_CHANGE,
)
from ...services.receipt import DEFAULT_RECEIPT_TEMPLATE, RECEIPT_PLACEHOLDERS
from ...services.data_reset import reset_operational_data, operational_data_counts
from ...utils.user_account import parse_user_email, parse_user_phone
from ...utils.i18n import translated_receipt_placeholders

bp = Blueprint("admin", __name__)


@bp.route("/")
@login_required
@admin_required
def index():
    return redirect(url_for("admin.settings"))


# ------------------------ SETTINGS ----------------------------------------- #

@bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    s = Settings.get()
    section = request.args.get("section", "branding")

    if request.method == "POST":
        form = request.form
        action = form.get("action")
        section = form.get("section", section)

        if action == "download":
            data, fname = create_backup_zip()
            log_audit("backup.download", entity="system")
            db.session.commit()
            return send_file(
                BytesIO(data),
                mimetype="application/zip",
                as_attachment=True,
                download_name=fname,
            )
        if action == "restore":
            f = request.files.get("file")
            if not f or not f.filename:
                flash("Выберите файл архива", "error")
                return redirect(url_for("admin.settings", section="backup"))
            ok, msg = restore_backup_zip(f)
            log_audit("backup.restore", entity="system", details=msg)
            db.session.commit()
            flash(msg, "success" if ok else "error")
            return redirect(url_for("admin.settings", section="backup"))

        if section == "backup":
            return redirect(url_for("admin.settings", section="backup"))

        if section == "branding":
            s.company_name = form.get("company_name", "").strip()
            s.company_tagline = form.get("company_tagline", "").strip()
            s.company_address = form.get("company_address", "").strip()
            s.company_phone = form.get("company_phone", "").strip()
            s.company_email = form.get("company_email", "").strip()
            s.company_tax_id = form.get("company_tax_id", "").strip()
            s.company_website = form.get("company_website", "").strip()
            s.company_waze = form.get("company_waze", "").strip()
            logo = request.files.get("company_logo")
            if logo and logo.filename:
                rel = save_upload(logo, subdir="branding", allowed=ALLOWED_IMAGE)
                if rel:
                    s.company_logo = rel
            if request.form.get("remove_logo"):
                s.company_logo = None

        elif section == "general":
            s.default_language = form.get("default_language") or "az"
            s.default_currency = form.get("default_currency") or "AZN"
            s.timezone = form.get("timezone") or "Asia/Baku"

        elif section == "finance":
            s.set_vat_mode(bool(form.get("vat_add_on_top")))
            s.vat_rate = float(form.get("vat_rate") or 0)

        elif section == "bonus":
            s.bonus_enabled = bool(form.get("bonus_enabled"))
            s.bonus_cashback_percent = float(form.get("bonus_cashback_percent") or 0)
            s.bonus_max_percent_of_order = float(form.get("bonus_max_percent_of_order") or 0)
            s.bonus_level_silver_threshold = float(form.get("bonus_level_silver_threshold") or 0)
            s.bonus_level_gold_threshold = float(form.get("bonus_level_gold_threshold") or 0)
            s.bonus_level_platinum_threshold = float(form.get("bonus_level_platinum_threshold") or 0)

        elif section == "azericard":
            s.azericard_enabled = bool(form.get("azericard_enabled"))
            s.azericard_merchant_id = form.get("azericard_merchant_id", "").strip()
            s.azericard_terminal_id = form.get("azericard_terminal_id", "").strip()
            s.azericard_merchant_name = form.get("azericard_merchant_name", "").strip()
            s.azericard_merchant_url = form.get("azericard_merchant_url", "").strip()
            s.azericard_email = form.get("azericard_email", "").strip()
            s.azericard_merch_gmt = form.get("azericard_merch_gmt", "").strip() or "+4"
            s.azericard_gateway_url = form.get("azericard_gateway_url", "").strip()
            s.azericard_currency = form.get("azericard_currency", "").strip() or "944"
            s.azericard_country = form.get("azericard_country", "").strip() or "AZ"
            s.azericard_test_mode = bool(form.get("azericard_test_mode"))
            s.azericard_client_portal_enabled = bool(form.get("azericard_client_portal_enabled"))
            new_priv = (form.get("azericard_private_key_pem") or "").strip()
            if new_priv:
                s.azericard_private_key_pem = new_priv
            new_pub = (form.get("azericard_public_key_pem") or "").strip()
            if new_pub:
                s.azericard_public_key_pem = new_pub
            # Legacy field: only update if explicitly posted non-empty
            legacy = (form.get("azericard_secret_key") or "").strip()
            if legacy:
                s.azericard_secret_key = legacy

        elif section == "evolution":
            s.evolution_enabled = bool(form.get("evolution_enabled"))
            s.evolution_base_url = form.get("evolution_base_url", "").strip()
            s.evolution_api_key = form.get("evolution_api_key", "").strip()
            s.evolution_instance_name = form.get("evolution_instance_name", "").strip()
            s.evolution_default_country_code = form.get("evolution_default_country_code", "994").strip()
            s.evolution_send_on_booking = bool(form.get("evolution_send_on_booking"))
            s.evolution_send_on_ready = bool(form.get("evolution_send_on_ready"))
            s.evolution_send_reminders = bool(form.get("evolution_send_reminders"))
            s.evolution_send_on_status_change = bool(form.get("evolution_send_on_status_change"))
            s.evolution_reminder_days = int(form.get("evolution_reminder_days") or 30)
            s.wa_template_ready = form.get("wa_template_ready", "").strip()
            s.wa_template_booking = form.get("wa_template_booking", "").strip()
            s.wa_template_reminder = form.get("wa_template_reminder", "").strip()
            s.wa_template_payment = form.get("wa_template_payment", "").strip()
            s.wa_template_status_change = form.get("wa_template_status_change", "").strip()
        elif section == "receipt":
            s.receipt_template = form.get("receipt_template", "").strip()
            s.receipt_cashier_name = form.get("receipt_cashier_name", "").strip()
            s.receipt_footer_note = form.get("receipt_footer_note", "").strip()

        log_audit("settings.update", entity="settings", details=section)
        db.session.commit()
        from ...utils.i18n import translate
        flash(translate("flash.settings_saved"), "success")
        return redirect(url_for("admin.settings", section=section))

    backup_logs = []
    if section == "backup":
        backup_logs = (
            AuditLog.query.filter(AuditLog.action.like("backup.%"))
            .order_by(AuditLog.created_at.desc())
            .limit(20)
            .all()
        )

    reset_counts = operational_data_counts() if section == "reset" else None
    wa_custom_templates = (
        WaMessageTemplate.query.order_by(
            WaMessageTemplate.sort_order, WaMessageTemplate.name
        ).all()
        if section == "evolution"
        else []
    )
    promo_codes = (
        PromoCode.query.order_by(PromoCode.created_at.desc()).all()
        if section == "bonus"
        else []
    )

    return render_template(
        "admin/settings.html",
        s=s,
        section=section,
        backup_logs=backup_logs,
        reset_counts=reset_counts,
        default_wa_ready=DEFAULT_WA_READY,
        default_wa_booking=DEFAULT_WA_BOOKING,
        default_wa_reminder=DEFAULT_WA_REMINDER,
        default_wa_payment=DEFAULT_WA_PAYMENT,
        default_wa_status_change=DEFAULT_WA_STATUS_CHANGE,
        default_receipt_template=DEFAULT_RECEIPT_TEMPLATE,
        receipt_placeholders=translated_receipt_placeholders(),
        wa_custom_templates=wa_custom_templates,
        promo_codes=promo_codes,
    )


@bp.post("/settings/wa-templates")
@login_required
@admin_required
def wa_template_save():
    tid = request.form.get("id")
    name = (request.form.get("name") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not name or not body:
        flash("Укажите название и текст шаблона", "error")
        return redirect(url_for("admin.settings", section="evolution"))
    if tid:
        tpl = db.session.get(WaMessageTemplate, int(tid)) or abort(404)
    else:
        tpl = WaMessageTemplate()
        db.session.add(tpl)
    tpl.name = name
    tpl.body = body
    tpl.sort_order = int(request.form.get("sort_order") or tpl.sort_order or 0)
    tpl.is_active = bool(request.form.get("is_active", "1"))
    log_audit(
        "wa_template.save",
        entity="wa_template",
        entity_id=tpl.id,
        details=name,
    )
    db.session.commit()
    flash("Шаблон сохранён", "success")
    return redirect(url_for("admin.settings", section="evolution"))


@bp.post("/settings/wa-templates/<int:tid>/delete")
@login_required
@admin_required
def wa_template_delete(tid: int):
    tpl = db.session.get(WaMessageTemplate, tid) or abort(404)
    log_audit("wa_template.delete", entity="wa_template", entity_id=tid, details=tpl.name)
    db.session.delete(tpl)
    db.session.commit()
    flash("Шаблон удалён", "success")
    return redirect(url_for("admin.settings", section="evolution"))


@bp.get("/settings/promo-codes/generate")
@login_required
@admin_required
def promo_code_generate():
    length = request.args.get("length", 6, type=int)
    try:
        code = generate_promo_code(length)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"code": code})


@bp.post("/settings/promo-codes")
@login_required
@admin_required
def promo_code_save():
    tid = request.form.get("id")
    raw_code = request.form.get("code") or ""
    code = normalize_promo_code(raw_code)
    if not code or len(code) < 4 or len(code) > 8:
        flash("Код промокода: от 4 до 8 символов (буквы и цифры)", "error")
        return redirect(url_for("admin.settings", section="bonus"))
    if not code.isalnum():
        flash("Промокод может содержать только буквы и цифры", "error")
        return redirect(url_for("admin.settings", section="bonus"))

    dtype = (request.form.get("discount_type") or "fixed").strip()
    if dtype not in ("fixed", "percent"):
        dtype = "fixed"
    discount_value = float(request.form.get("discount_value") or 0)
    if discount_value <= 0:
        flash("Укажите положительную скидку", "error")
        return redirect(url_for("admin.settings", section="bonus"))

    valid_until_raw = (request.form.get("valid_until") or "").strip()
    valid_until = None
    if valid_until_raw:
        try:
            valid_until = datetime.strptime(valid_until_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Неверный формат даты окончания", "error")
            return redirect(url_for("admin.settings", section="bonus"))

    max_uses = int(request.form.get("max_uses") or 0)
    if max_uses < 0:
        max_uses = 0

    if tid:
        promo = db.session.get(PromoCode, int(tid)) or abort(404)
        existing = PromoCode.query.filter(PromoCode.code == code, PromoCode.id != promo.id).first()
    else:
        promo = PromoCode()
        db.session.add(promo)
        existing = PromoCode.query.filter_by(code=code).first()

    if existing:
        flash("Промокод с таким кодом уже существует", "error")
        return redirect(url_for("admin.settings", section="bonus"))

    promo.code = code
    promo.discount_type = dtype
    promo.discount_value = discount_value
    promo.valid_until = valid_until
    promo.max_uses = max_uses
    promo.is_active = bool(request.form.get("is_active", "1"))
    log_audit(
        "promo_code.save",
        entity="promo_code",
        entity_id=promo.id,
        details=code,
    )
    db.session.commit()
    flash("Промокод сохранён", "success")
    return redirect(url_for("admin.settings", section="bonus"))


@bp.post("/settings/promo-codes/<int:pid>/delete")
@login_required
@admin_required
def promo_code_delete(pid: int):
    promo = db.session.get(PromoCode, pid) or abort(404)
    Order.query.filter_by(promo_code_id=pid).update(
        {Order.promo_code_id: None},
        synchronize_session=False,
    )
    log_audit("promo_code.delete", entity="promo_code", entity_id=pid, details=promo.code)
    db.session.delete(promo)
    db.session.commit()
    flash("Промокод удалён", "success")
    return redirect(url_for("admin.settings", section="bonus"))


@bp.post("/settings/reset")
@login_required
@admin_required
def settings_reset():
    if not current_user.is_admin:
        abort(403)

    password = request.form.get("password") or ""
    admin = db.session.get(User, current_user.id)
    if not admin or not admin.check_password(password):
        flash("Неверный пароль администратора", "error")
        return redirect(url_for("admin.settings", section="reset"))

    try:
        stats = reset_operational_data(current_app.config["UPLOAD_FOLDER"])
    except Exception as exc:
        db.session.rollback()
        flash(f"Сброс не выполнен: {exc}", "error")
        return redirect(url_for("admin.settings", section="reset"))

    log_audit(
        "data.reset",
        entity="system",
        details=(
            f"заказов {stats.get('orders', 0)}, журналов заказов {stats.get('order_audit_logs', 0)}, "
            f"оплат {stats.get('payments', 0)}, движений склада {stats.get('movements', 0)}, "
            f"зарплат {stats.get('salaries', 0)}"
        ),
    )
    db.session.commit()
    flash(
        "Операционные данные сброшены: заказы, журналы заказов, выручка, расходы материалов, бонусы и ведомости.",
        "success",
    )
    return redirect(url_for("admin.settings", section="reset"))


@bp.post("/settings/evolution/test")
@login_required
@admin_required
def evolution_test():
    svc = EvolutionAPIService()
    ok, msg = svc.instance_status()
    flash(f"WhatsApp: {'OK' if ok else 'Ошибка'} — {msg[:200]}", "success" if ok else "error")
    return redirect(url_for("admin.settings", section="evolution"))


# ------------------------ USERS -------------------------------------------- #

@bp.route("/users")
@login_required
@admin_required
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, roles=list(Role))


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def user_new():
    if request.method == "POST":
        email, email_err = parse_user_email(request.form.get("email", ""))
        if email_err:
            flash(email_err, "error")
            return redirect(url_for("admin.user_new"))
        name = request.form.get("name", "").strip()
        role = _valid_role(request.form.get("role"))
        password = request.form.get("password") or ""
        phone, phone_err = parse_user_phone(request.form.get("phone", ""))
        if phone_err:
            flash(phone_err, "error")
            return redirect(url_for("admin.user_new"))
        if not (name and password):
            flash("Заполните имя и пароль", "error")
            return redirect(url_for("admin.user_new"))
        if User.query.filter_by(email=email).first():
            flash("Email уже занят", "error")
            return redirect(url_for("admin.user_new"))
        if phone and User.query.filter_by(phone=phone).first():
            flash("Телефон уже привязан к другому пользователю", "error")
            return redirect(url_for("admin.user_new"))
        branch_raw = request.form.get("branch_id")
        branch_id = int(branch_raw) if branch_raw else None
        u = User(email=email, name=name, role=role, phone=phone, branch_id=branch_id)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        log_audit(
            "user.create",
            entity="user",
            entity_id=u.id,
            details=f"{u.name} · {email}" + (f" · {phone}" if phone else ""),
        )
        db.session.commit()
        flash("Пользователь создан", "success")
        return redirect(url_for("admin.users"))
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    return render_template("admin/user_form.html", user=None, roles=list(Role), branches=branches)


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(uid: int):
    u = db.session.get(User, uid) or abort(404)
    editing_self = u.id == current_user.id
    if request.method == "GET" and editing_self:
        return redirect(url_for("auth.profile"))
    if request.method == "POST":
        u.name = request.form.get("name", u.name).strip()
        email, email_err = parse_user_email(request.form.get("email", ""))
        if email_err:
            flash(email_err, "error")
            return redirect(url_for("admin.user_edit", uid=uid))
        if email != u.email:
            dup = User.query.filter(User.email == email, User.id != u.id).first()
            if dup:
                flash("Email уже используется другим пользователем", "error")
                return redirect(url_for("admin.user_edit", uid=uid))
            u.email = email
        if not editing_self:
            u.role = _valid_role(request.form.get("role"), default=u.role)
            u.is_active = bool(request.form.get("is_active"))
            branch_raw = request.form.get("branch_id")
            u.branch_id = int(branch_raw) if branch_raw else None
        phone, phone_err = parse_user_phone(request.form.get("phone", ""))
        if phone_err:
            flash(phone_err, "error")
            return redirect(url_for("admin.user_edit", uid=uid))
        if phone:
            dup = User.query.filter(User.phone == phone, User.id != u.id).first()
            if dup:
                flash("Телефон уже используется другим пользователем", "error")
                return redirect(url_for("admin.user_edit", uid=uid))
        u.phone = phone
        new_pwd = request.form.get("password")
        if new_pwd:
            u.set_password(new_pwd)
        log_audit(
            "user.update",
            entity="user",
            entity_id=u.id,
            details=f"{u.name} · {u.email}" + (f" · {u.phone}" if u.phone else "")
            + ("" if editing_self else f" · роль {u.role}"),
        )
        db.session.commit()
        flash("Профиль обновлён" if editing_self else "Пользователь обновлён", "success")
        if editing_self:
            return redirect(url_for("auth.profile"))
        return redirect(url_for("admin.users"))
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    return render_template("admin/user_form.html", user=u, roles=list(Role), branches=branches)


@bp.post("/users/<int:uid>/delete")
@login_required
@admin_required
def user_delete(uid: int):
    u = db.session.get(User, uid) or abort(404)
    if u.id == current_user.id:
        flash("Нельзя удалить себя", "error")
        return redirect(url_for("admin.users"))
    db.session.delete(u)
    log_audit("user.delete", entity="user", entity_id=uid, details=f"{u.name} · {u.email}")
    db.session.commit()
    flash("Пользователь удалён", "success")
    return redirect(url_for("admin.users"))


# ------------------------ BRANCHES ----------------------------------------- #

def _apply_branch_form(b: Branch) -> bool:
    name = request.form.get("name", "").strip()
    if not name:
        flash("Укажите название филиала", "error")
        return False
    b.name = name
    b.address = request.form.get("address", "").strip()
    b.phone = request.form.get("phone", "").strip()
    b.is_active = bool(request.form.get("is_active"))
    return True


@bp.route("/branches", methods=["GET", "POST"])
@login_required
@admin_required
def branches():
    if request.method == "POST":
        b = Branch()
        if not _apply_branch_form(b):
            return redirect(url_for("admin.branches"))
        db.session.add(b)
        db.session.flush()
        log_audit("branch.save", entity="branch", entity_id=b.id)
        db.session.commit()
        flash("Филиал сохранён", "success")
        return redirect(url_for("admin.branches"))
    branches = Branch.query.order_by(Branch.name).all()
    return render_template("admin/branches.html", branches=branches)


@bp.route("/branches/<int:bid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def branch_edit(bid: int):
    b = db.session.get(Branch, bid)
    if not b:
        abort(404)
    if request.method == "POST":
        if not _apply_branch_form(b):
            return redirect(url_for("admin.branch_edit", bid=bid))
        log_audit("branch.save", entity="branch", entity_id=b.id)
        db.session.commit()
        flash("Филиал сохранён", "success")
        return redirect(url_for("admin.branches"))
    bays = (
        Bay.query.filter_by(branch_id=b.id)
        .order_by(Bay.sort_order, Bay.id)
        .all()
    )
    return render_template(
        "admin/branch_form.html",
        branch=b,
        bays=bays,
        bay_types=BayType,
        bay_type_labels=BAY_TYPE_LABELS,
    )


def _bay_types_from_form() -> set[str]:
    valid = {t.value for t in BayType}
    return {t for t in request.form.getlist("bay_types") if t in valid}


def _sync_bay_capabilities(bay: Bay, types: set[str]) -> None:
    BayCapability.query.filter_by(bay_id=bay.id).delete()
    for t in types:
        db.session.add(BayCapability(bay_id=bay.id, bay_type=t))


@bp.post("/branches/<int:bid>/bays/add")
@login_required
@admin_required
def branch_bay_add(bid: int):
    branch = db.session.get(Branch, bid) or abort(404)
    name = request.form.get("bay_name", "").strip()
    if not name:
        flash("Укажите название бокса", "error")
        return redirect(url_for("admin.branch_edit", bid=bid))
    types = _bay_types_from_form()
    if not types:
        flash("Выберите хотя бы один тип бокса", "error")
        return redirect(url_for("admin.branch_edit", bid=bid))
    max_sort = db.session.query(func.max(Bay.sort_order)).filter_by(branch_id=bid).scalar() or 0
    bay = Bay(branch_id=branch.id, name=name, sort_order=max_sort + 1, is_active=True)
    db.session.add(bay)
    db.session.flush()
    for t in types:
        db.session.add(BayCapability(bay_id=bay.id, bay_type=t))
    log_audit("branch.bay_add", entity="bay", entity_id=bay.id, details=f"{branch.name}: {name}")
    db.session.commit()
    flash("Бокс добавлен", "success")
    return redirect(url_for("admin.branch_edit", bid=bid))


@bp.post("/branches/<int:bid>/bays/<int:bay_id>/edit")
@login_required
@admin_required
def branch_bay_edit(bid: int, bay_id: int):
    branch = db.session.get(Branch, bid) or abort(404)
    bay = db.session.get(Bay, bay_id) or abort(404)
    if bay.branch_id != branch.id:
        abort(404)
    name = request.form.get("bay_name", "").strip()
    if not name:
        flash("Укажите название бокса", "error")
        return redirect(url_for("admin.branch_edit", bid=bid))
    types = _bay_types_from_form()
    if not types:
        flash("Выберите хотя бы один тип бокса", "error")
        return redirect(url_for("admin.branch_edit", bid=bid))
    bay.name = name
    bay.is_active = bool(request.form.get("is_active"))
    sort = request.form.get("sort_order")
    if sort is not None and str(sort).strip() != "":
        bay.sort_order = int(sort)
    _sync_bay_capabilities(bay, types)
    log_audit("branch.bay_edit", entity="bay", entity_id=bay.id, details=name)
    db.session.commit()
    flash("Бокс обновлён", "success")
    return redirect(url_for("admin.branch_edit", bid=bid))


@bp.post("/branches/<int:bid>/bays/<int:bay_id>/delete")
@login_required
@admin_required
def branch_bay_delete(bid: int, bay_id: int):
    branch = db.session.get(Branch, bid) or abort(404)
    bay = db.session.get(Bay, bay_id) or abort(404)
    if bay.branch_id != branch.id:
        abort(404)
    if bay.orders:
        flash("Нельзя удалить бокс с привязанными заказами", "error")
        return redirect(url_for("admin.branch_edit", bid=bid))
    db.session.delete(bay)
    log_audit("branch.bay_delete", entity="bay", entity_id=bay_id, details=bay.name)
    db.session.commit()
    flash("Бокс удалён", "success")
    return redirect(url_for("admin.branch_edit", bid=bid))


# ------------------------ BACKUP ------------------------------------------- #

@bp.route("/backup", methods=["GET", "POST"])
@login_required
@admin_required
def backup():
    """Legacy URL — backup moved to Settings."""
    if request.method == "POST":
        return settings()
    return redirect(url_for("admin.settings", section="backup"))


# ------------------------ AZERICARD LOG ------------------------------------ #

@bp.route("/azericard/logs")
@login_required
@admin_required
def azericard_logs():
    from ...models.azericard import AzericardLog

    logs = AzericardLog.query.order_by(AzericardLog.id.desc()).limit(200).all()
    return render_template("admin/azericard_logs.html", logs=logs)


# ------------------------ AUDIT LOG ---------------------------------------- #

@bp.route("/audit")
@login_required
@admin_required
def audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin/audit.html", logs=logs)
