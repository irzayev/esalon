from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, make_response
from flask_login import login_user, logout_user, login_required, current_user

from ...extensions import db, limiter
from ...models.user import User
from ...utils.auth_redirect import home_endpoint_for, safe_next
from ...utils.audit import log_audit
from ...utils.client_fields import parse_phone_form
from ...utils.country_dial_codes import DEFAULT_DIAL_CODE
from ...utils.user_account import parse_user_email, parse_user_phone
from ...utils.i18n import set_locale, translate, SUPPORTED_LOCALES, COOKIE_KEY

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(home_endpoint_for(current_user)))

    form = {
        "login_method": "phone",
        "email": "",
        "phone_dial": DEFAULT_DIAL_CODE,
        "phone_local": "",
    }

    if request.method == "POST":
        login_method = (request.form.get("login_method") or "phone").strip()
        if login_method == "email":
            login_id = (request.form.get("email") or "").strip().lower()
        else:
            login_id = parse_phone_form(request.form)
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))

        form.update(
            login_method=login_method,
            email=request.form.get("email") or "",
            phone_dial=request.form.get("phone_dial_code") or DEFAULT_DIAL_CODE,
            phone_local=request.form.get("phone_local") or "",
        )

        user = User.find_by_login(login_id)
        if user and user.is_active and user.check_password(password):
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            return redirect(safe_next(request.args.get("next")) or url_for(home_endpoint_for(user)))
        flash(translate("login.error"), "error")

    return render_template("auth/login.html", form=form)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = db.session.get(User, current_user.id) or abort(404)
    if request.method == "POST":
        u.name = request.form.get("name", u.name).strip()
        if not u.name:
            flash("Укажите имя", "error")
            return redirect(url_for("auth.profile"))
        email, email_err = parse_user_email(request.form.get("email", ""))
        if email_err:
            flash(email_err, "error")
            return redirect(url_for("auth.profile"))
        if email != u.email:
            dup = User.query.filter(User.email == email, User.id != u.id).first()
            if dup:
                flash("Email уже используется другим пользователем", "error")
                return redirect(url_for("auth.profile"))
            u.email = email
        phone, phone_err = parse_user_phone(request.form.get("phone", ""))
        if phone_err:
            flash(phone_err, "error")
            return redirect(url_for("auth.profile"))
        if phone:
            dup = User.query.filter(User.phone == phone, User.id != u.id).first()
            if dup:
                flash("Телефон уже используется другим пользователем", "error")
                return redirect(url_for("auth.profile"))
        u.phone = phone
        new_pwd = request.form.get("password")
        if new_pwd:
            u.set_password(new_pwd)
            u.must_change_password = False
        log_audit(
            "user.update",
            entity="user",
            entity_id=u.id,
            details=f"Профиль: {u.name} · {u.email}" + (f" · {u.phone}" if u.phone else ""),
        )
        db.session.commit()
        flash(translate("flash.profile_updated"), "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", user=u)


@bp.get("/locale/<lang>")
def switch_locale(lang: str):
    loc = set_locale(lang)
    dest = request.args.get("next") or request.referrer
    if not dest:
        dest = url_for("auth.login")
    else:
        try:
            from urllib.parse import urlparse
            ref = urlparse(dest)
            req = urlparse(request.host_url)
            if ref.netloc and ref.netloc != req.netloc:
                dest = url_for("auth.login")
        except Exception:
            dest = url_for("auth.login")
    resp = make_response(redirect(dest))
    resp.set_cookie(COOKIE_KEY, loc, max_age=365 * 24 * 3600, samesite="Lax", path="/")
    return resp


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
