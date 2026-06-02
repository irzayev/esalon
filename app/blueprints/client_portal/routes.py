"""Public client order view: phone + order number mini-auth."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ...extensions import db, limiter
from ...models.bonus import BonusWallet
from ...models.order import recalc_order_totals
from ...models.settings import Settings
from ...utils.audit import log_audit
from ...services.client_portal_payment import (
    client_portal_pay_available,
    client_visible_payments,
    get_or_create_client_pay_url,
)
from ...services.receipt import _payment_totals, render_receipt_html
from ...services.scheduling import order_slot_bounds, utc_naive_to_local
from ...utils.client_fields import normalize_phone, parse_phone_form
from ...utils.client_order_access import (
    grant_client_order_access,
    revoke_client_order_access,
    has_client_order_access,
    verify_order_credentials,
    get_client_audit_logs,
)
from ...utils.i18n import translate
from ...utils.order_lookup import get_order_by_number_public, is_valid_order_number

bp = Blueprint("client_portal", __name__, url_prefix="/track")


def _client_bonuses_enabled() -> bool:
    s = Settings.get()
    return bool(s.bonus_enabled and s.bonus_client_portal_enabled)


def _client_order_or_redirect(number: str):
    if not is_valid_order_number(number):
        abort(404)
    if not has_client_order_access(number):
        flash(translate("track.error.session"), "error")
        return None, redirect(url_for("client_portal.index", number=number))
    order = get_order_by_number_public(number)
    if not order:
        abort(404)
    return order, None


@bp.route("/", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def index():
    prefill_number = (request.args.get("number") or "").strip()
    phone_dial = None
    phone_local = ""
    if request.method == "POST":
        number = (request.form.get("number") or "").strip()
        phone = parse_phone_form(request.form)
        order, err_key = verify_order_credentials(number, phone)
        if order:
            grant_client_order_access(order.number, normalize_phone(phone))
            return redirect(url_for("client_portal.view", number=order.number))
        flash(translate(err_key or "track.error.invalid"), "error")
        prefill_number = number
        phone_dial = (request.form.get("phone_dial_code") or "").strip() or None
        phone_local = (request.form.get("phone_local") or "").strip()

    return render_template(
        "client/track_form.html",
        prefill_number=prefill_number,
        phone_dial=phone_dial,
        phone_local=phone_local,
    )


@bp.route("/<order_number:number>")
def view(number: str):
    if not is_valid_order_number(number):
        abort(404)
    if not has_client_order_access(number):
        flash(translate("track.error.session"), "error")
        return redirect(url_for("client_portal.index", number=number))

    order = get_order_by_number_public(number)
    if not order:
        abort(404)

    slot_start, slot_end = order_slot_bounds(order)
    slot_start_local = utc_naive_to_local(slot_start)
    slot_end_local = utc_naive_to_local(slot_end)
    activity_logs = get_client_audit_logs(order.id)

    settings = Settings.get()
    return render_template(
        "client/track_detail.html",
        order=order,
        settings=settings,
        slot_start_local=slot_start_local,
        slot_end_local=slot_end_local,
        activity_logs=activity_logs,
        pay_online_available=client_portal_pay_available(order),
        visible_payments=client_visible_payments(order),
        client_bonuses_enabled=_client_bonuses_enabled(),
    )


@bp.get("/<order_number:number>/receipt")
def receipt(number: str):
    if not is_valid_order_number(number):
        abort(404)
    if not has_client_order_access(number):
        flash(translate("track.error.session"), "error")
        return redirect(url_for("client_portal.index", number=number))

    order = get_order_by_number_public(number)
    if not order:
        abort(404)

    settings = Settings.get()
    payment_totals = _payment_totals(order)
    receipt_html = render_receipt_html(
        order,
        settings,
        payment_totals=payment_totals,
    )
    return render_template(
        "client/track_receipt.html",
        order=order,
        settings=settings,
        receipt_html=receipt_html,
    )


@bp.post("/<order_number:number>/pay")
@limiter.limit("5 per minute")
def start_pay(number: str):
    if not is_valid_order_number(number):
        abort(404)
    if not has_client_order_access(number):
        flash(translate("track.error.session"), "error")
        return redirect(url_for("client_portal.index", number=number))

    order = get_order_by_number_public(number)
    if not order:
        abort(404)
    if not client_portal_pay_available(order):
        return redirect(url_for("client_portal.view", number=number))

    pay_url = get_or_create_client_pay_url(order)
    if not pay_url:
        return redirect(url_for("client_portal.view", number=number))
    return redirect(pay_url)


@bp.post("/<order_number:number>/logout")
def logout(number: str):
    revoke_client_order_access(number)
    flash(translate("track.logout_done"), "success")
    return redirect(url_for("client_portal.index"))


@bp.post("/<order_number:number>/bonus")
@limiter.limit("10 per minute")
def apply_bonus(number: str):
    result = _client_order_or_redirect(number)
    order, redirect_resp = result
    if redirect_resp:
        return redirect_resp
    if not _client_bonuses_enabled():
        flash(translate("track.bonus_disabled"), "error")
        return redirect(url_for("client_portal.view", number=number))
    if order.is_paid:
        flash(translate("promo.error.order_paid"), "error")
        return redirect(url_for("client_portal.view", number=number))

    raw = float(request.form.get("amount") or 0)
    if raw < 0:
        flash(translate("track.bonus_negative"), "error")
        return redirect(url_for("client_portal.view", number=number))

    s = Settings.get()
    max_allowed = (order.subtotal or 0) * (s.bonus_max_percent_of_order / 100)
    wallet = order.client.wallet
    if not wallet:
        wallet = BonusWallet(client_id=order.client_id)
        db.session.add(wallet)
        db.session.commit()
    amount = max(0.0, min(raw, max_allowed, wallet.balance or 0))
    order.bonus_used = amount
    log_audit(
        "order.bonus",
        entity="order",
        entity_id=order.id,
        details=f"Client portal: {amount:.2f}",
    )
    db.session.commit()
    recalc_order_totals(order)
    flash(translate("track.bonus_applied", amount=f"{amount:.2f}"), "success")
    return redirect(url_for("client_portal.view", number=number))


@bp.post("/<order_number:number>/promo")
@limiter.limit("10 per minute")
def apply_promo(number: str):
    result = _client_order_or_redirect(number)
    order, redirect_resp = result
    if redirect_resp:
        return redirect_resp
    if not _client_bonuses_enabled():
        flash(translate("track.bonus_disabled"), "error")
        return redirect(url_for("client_portal.view", number=number))
    if order.is_paid:
        flash(translate("promo.error.order_paid"), "error")
        return redirect(url_for("client_portal.view", number=number))

    from ...services.promo_code import normalize_promo_code, validate_promo_code

    raw = request.form.get("code") or ""
    promo, err_key = validate_promo_code(raw)
    if not promo:
        flash(translate(err_key or "promo.error.not_found"), "error")
        return redirect(url_for("client_portal.view", number=number))

    order.promo_code_id = promo.id
    order.promo_code_text = normalize_promo_code(raw)
    order.promo_discount_type = promo.discount_type
    order.promo_discount_value = promo.discount_value
    order.promo_use_counted = False
    log_audit(
        "order.discount",
        entity="order",
        entity_id=order.id,
        details=f"Client portal promo {order.promo_code_text}",
    )
    db.session.commit()
    recalc_order_totals(order)
    flash(translate("promo.applied", code=order.promo_code_text), "success")
    return redirect(url_for("client_portal.view", number=number))


@bp.post("/<order_number:number>/promo/remove")
@limiter.limit("10 per minute")
def remove_promo(number: str):
    result = _client_order_or_redirect(number)
    order, redirect_resp = result
    if redirect_resp:
        return redirect_resp
    if not _client_bonuses_enabled():
        flash(translate("track.bonus_disabled"), "error")
        return redirect(url_for("client_portal.view", number=number))
    if order.is_paid:
        flash(translate("promo.error.order_paid"), "error")
        return redirect(url_for("client_portal.view", number=number))
    if not order.promo_code_id:
        return redirect(url_for("client_portal.view", number=number))

    code = order.promo_code_text or "—"
    order.promo_code_id = None
    order.promo_code_text = None
    order.promo_discount_type = None
    order.promo_discount_value = 0
    order.promo_use_counted = False
    log_audit(
        "order.discount",
        entity="order",
        entity_id=order.id,
        details=f"Client portal promo removed {code}",
    )
    db.session.commit()
    recalc_order_totals(order)
    flash(translate("promo.removed"), "success")
    return redirect(url_for("client_portal.view", number=number))
