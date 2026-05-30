"""Public client order view: phone + order number mini-auth."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ...extensions import limiter
from ...models.settings import Settings
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


@bp.route("/<number>")
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
    )


@bp.post("/<number>/logout")
def logout(number: str):
    revoke_client_order_access(number)
    flash(translate("track.logout_done"), "success")
    return redirect(url_for("client_portal.index"))
