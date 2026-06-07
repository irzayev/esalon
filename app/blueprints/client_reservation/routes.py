"""Public reservation form: phone, car type, services/package → NEW order."""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, flash

from ...extensions import limiter
from ...models.client import CarBodyType
from ...models.settings import Settings
from ...services.client_reservation import (
    _local_today,
    _parse_service_ids,
    create_reservation,
    list_offerings_for_body_type,
    list_slots_for_selection,
    lookup_client_by_phone,
)
from ...utils.client_fields import normalize_phone, parse_phone_form
from ...utils.client_order_access import grant_client_order_access
from ...utils.i18n import get_body_type_choices, translate

bp = Blueprint("client_reservation", __name__, url_prefix="/reservation")

_VALID_BODY_TYPES = {t.value for t in CarBodyType}


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
    body_type_choices = get_body_type_choices()
    selected_body_type = (request.form.get("body_type") or request.args.get("body_type") or "").strip()
    if selected_body_type not in _VALID_BODY_TYPES:
        selected_body_type = CarBodyType.SEDAN.value

    phone_dial = None
    phone_local = ""
    selected_client_name = ""
    selected_package_id = None
    selected_service_ids: list[int] = []
    selected_schedule_date = ""
    selected_schedule_time = ""
    selected_bay_id = None

    if request.method == "POST":
        phone = parse_phone_form(request.form)
        body_type = (request.form.get("body_type") or "").strip()
        package_raw = (request.form.get("package_id") or "").strip()
        package_id = int(package_raw) if package_raw.isdigit() else None
        service_ids = _parse_service_ids(request.form.getlist("service_ids"))

        schedule_date = (request.form.get("schedule_date") or "").strip()
        schedule_time = (request.form.get("schedule_time") or "").strip()
        bay_raw = (request.form.get("bay_id") or "").strip()
        bay_id = int(bay_raw) if bay_raw.isdigit() else None

        order, err_key = create_reservation(
            phone=phone,
            client_name=(request.form.get("client_name") or "").strip() or None,
            body_type=body_type,
            service_ids=service_ids,
            package_id=package_id,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            bay_id=bay_id,
        )
        if order:
            grant_client_order_access(order.number, normalize_phone(phone))
            return redirect(url_for("client_reservation.success", number=order.number))

        flash(translate(err_key or "reservation.error.generic"), "error")
        selected_body_type = body_type if body_type in _VALID_BODY_TYPES else selected_body_type
        phone_dial = (request.form.get("phone_dial_code") or "").strip() or None
        phone_local = (request.form.get("phone_local") or "").strip()
        selected_client_name = (request.form.get("client_name") or "").strip()
        selected_package_id = package_id
        selected_service_ids = service_ids
        selected_schedule_date = schedule_date
        selected_schedule_time = schedule_time
        selected_bay_id = bay_id

    offerings = list_offerings_for_body_type(selected_body_type)
    currency = settings.default_currency or "AZN"
    money_symbol = "₼" if currency.upper() in ("AZN", "₼") else currency
    return render_template(
        "client/reservation_form.html",
        settings=settings,
        body_type_choices=body_type_choices,
        selected_body_type=selected_body_type,
        offerings=offerings,
        phone_dial=phone_dial,
        phone_local=phone_local,
        selected_client_name=selected_client_name,
        selected_package_id=selected_package_id,
        selected_service_ids=selected_service_ids,
        selected_schedule_date=selected_schedule_date,
        selected_schedule_time=selected_schedule_time,
        selected_bay_id=selected_bay_id,
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
    client, err_key = lookup_client_by_phone(phone)
    if err_key:
        return _api_error(err_key)
    if client:
        return jsonify({"found": True, "name": client.name})
    return jsonify({"found": False})


@bp.get("/api/offerings")
@limiter.limit("60 per minute")
def api_offerings():
    body_type = (request.args.get("body_type") or "").strip()
    if body_type not in _VALID_BODY_TYPES:
        return _api_error("reservation.error.body_type")
    return jsonify(list_offerings_for_body_type(body_type))


@bp.get("/api/slots")
@limiter.limit("60 per minute")
def api_slots():
    body_type = (request.args.get("body_type") or "").strip()
    if body_type not in _VALID_BODY_TYPES:
        return _api_error("reservation.error.body_type")

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
        body_type=body_type,
        service_ids=service_ids,
        package_id=package_id,
        day=day,
    )
    if err_key:
        return _api_error(err_key)
    return jsonify({"slots": slots or [], "date": day_raw})
