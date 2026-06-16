"""Public reservation form: phone, procedures → NEW order."""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, flash

from ...extensions import limiter
from ...models.settings import Settings
from ...services.client_reservation import (
    _local_today,
    _parse_service_ids,
    create_reservation,
    list_offerings,
    list_slots_for_selection,
    lookup_client_by_phone,
)
from ...utils.client_fields import normalize_phone, parse_phone_form
from ...utils.client_order_access import grant_client_order_access
from ...utils.i18n import translate

bp = Blueprint("client_reservation", __name__, url_prefix="/reservation")


def _api_error(err_key: str, status: int = 400):
    return jsonify({"error": err_key, "message": translate(err_key)}), status


@bp.before_request
def _require_online_reservation_enabled():
    if not Settings.get().online_reservation_enabled:
        abort(404)


@bp.route("/", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def index():
    settings = Settings.get()

    phone_dial = None
    phone_local = ""
    selected_client_name = ""
    selected_package_id = None
    selected_service_ids: list[int] = []
    selected_schedule_date = ""
    selected_schedule_time = ""
    selected_cabinet_id = None

    if request.method == "POST":
        phone = parse_phone_form(request.form)
        package_raw = (request.form.get("package_id") or "").strip()
        package_id = int(package_raw) if package_raw.isdigit() else None
        service_ids = _parse_service_ids(request.form.getlist("service_ids"))

        schedule_date = (request.form.get("schedule_date") or "").strip()
        schedule_time = (request.form.get("schedule_time") or "").strip()
        cabinet_raw = (request.form.get("cabinet_id") or "").strip()
        cabinet_id = int(cabinet_raw) if cabinet_raw.isdigit() else None

        phone_local = (request.form.get("phone_local") or "").strip()
        order, err_key = create_reservation(
            phone=phone,
            phone_local=phone_local,
            client_name=(request.form.get("client_name") or "").strip() or None,
            service_ids=service_ids,
            package_id=package_id,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            cabinet_id=cabinet_id,
        )
        if order:
            grant_client_order_access(order.number, normalize_phone(phone))
            return redirect(url_for("client_reservation.success", number=order.number))

        flash(translate(err_key or "reservation.error.generic"), "error")
        phone_dial = (request.form.get("phone_dial_code") or "").strip() or None
        selected_client_name = (request.form.get("client_name") or "").strip()
        selected_package_id = package_id
        selected_service_ids = service_ids
        selected_schedule_date = schedule_date
        selected_schedule_time = schedule_time
        selected_cabinet_id = cabinet_id

    offerings = list_offerings()
    currency = settings.default_currency or "AZN"
    money_symbol = "₼" if currency.upper() in ("AZN", "₼") else currency
    return render_template(
        "client/reservation_form.html",
        settings=settings,
        offerings=offerings,
        phone_dial=phone_dial,
        phone_local=phone_local,
        selected_client_name=selected_client_name,
        selected_package_id=selected_package_id,
        selected_service_ids=selected_service_ids,
        selected_schedule_date=selected_schedule_date,
        selected_schedule_time=selected_schedule_time,
        selected_cabinet_id=selected_cabinet_id,
        min_schedule_date=_local_today().isoformat(),
        money_symbol=money_symbol,
        offerings_load_error=translate("reservation.offerings_load_error"),
        slots_load_error=translate("reservation.slots_load_error"),
    )


@bp.get("/success/<order_number:number>")
def success(number: str):
    settings = Settings.get()
    return render_template(
        "client/reservation_success.html",
        settings=settings,
        order_number=number,
    )


@bp.get("/api/client-lookup")
@limiter.limit("30 per minute")
def api_client_lookup():
    phone = (request.args.get("phone") or "").strip()
    if not phone:
        phone = parse_phone_form(request.args)
    phone_local = (request.args.get("phone_local") or "").strip() or None
    client, err_key = lookup_client_by_phone(phone, phone_local=phone_local)
    if err_key:
        return _api_error(err_key)
    if client:
        return jsonify({"found": True, "name": client.name})
    return jsonify({"found": False})


@bp.get("/api/offerings")
@limiter.limit("60 per minute")
def api_offerings():
    return jsonify(list_offerings())


@bp.get("/api/slots")
@limiter.limit("60 per minute")
def api_slots():
    package_raw = (request.args.get("package_id") or "").strip()
    package_id = int(package_raw) if package_raw.isdigit() else None
    service_ids = _parse_service_ids(request.args.getlist("service_ids"))
    if not service_ids and request.args.get("service_ids"):
        service_ids = _parse_service_ids([(request.args.get("service_ids") or "").strip()])

    from datetime import datetime

    day_raw = (request.args.get("date") or "").strip()
    try:
        day = datetime.strptime(day_raw, "%Y-%m-%d").date()
    except ValueError:
        return _api_error("reservation.error.invalid_slot")

    slots, err_key = list_slots_for_selection(
        service_ids=service_ids,
        package_id=package_id,
        day=day,
    )
    if err_key:
        return _api_error(err_key)
    return jsonify({"slots": slots or [], "date": day_raw})
