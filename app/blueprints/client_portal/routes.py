"""Public client order view: phone + order number mini-auth."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ...extensions import limiter
from ...models.settings import Settings
from ...services.client_portal_payment import (
    client_portal_pay_available,
    client_visible_payments,
    get_or_create_client_pay_url,
)
from ...services.receipt import _payment_totals, render_receipt_html
from ...services.scheduling import order_slot_bounds, utc_naive_to_local
from ...utils.client_fields import normalize_phone
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


@bp.route("/", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def index():
    prefill_number = (request.args.get("number") or "").strip()
    if request.method == "POST":
        number = (request.form.get("number") or "").strip()
        phone = request.form.get("phone") or ""
        order, err_key = verify_order_credentials(number, phone)
        if order:
            grant_client_order_access(order.number, normalize_phone(phone))
            return redirect(url_for("client_portal.view", number=order.number))
        flash(translate(err_key or "track.error.invalid"), "error")
        prefill_number = number

    return render_template(
        "client/track_form.html",
        prefill_number=prefill_number,
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

    return render_template(
        "client/track_detail.html",
        order=order,
        settings=Settings.get(),
        slot_start_local=slot_start_local,
        slot_end_local=slot_end_local,
        activity_logs=activity_logs,
        pay_online_available=client_portal_pay_available(order),
        visible_payments=client_visible_payments(order),
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
