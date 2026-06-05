"""Public reservation form: phone, car type, services/package → NEW order."""
from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash

from ...extensions import limiter
from ...models.client import CarBodyType
from ...models.settings import Settings
from ...services.client_reservation import (
    _local_today,
    _parse_service_ids,
    create_reservation,
    list_offerings_for_body_type,
    list_slots_for_selection,
)
from ...utils.client_fields import normalize_phone, parse_phone_form
from ...utils.client_order_access import grant_client_order_access
from ...utils.i18n import get_body_type_choices, translate

bp = Blueprint("client_reservation", __name__, url_prefix="/reservation")

_VALID_BODY_TYPES = {t.value for t in CarBodyType}


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

    offerings = list_offerings_for_body_type(selected_body_type)
    return render_template(
        "client/reservation_form.html",
        settings=settings,
        body_type_choices=body_type_choices,
        selected_body_type=selected_body_type,
        offerings=offerings,
        phone_dial=phone_dial,
        phone_local=phone_local,
        min_schedule_date=_local_today().isoformat(),
    )


@bp.get("/success/<order_number:number>")
def success(number: str):
    settings = Settings.get()
    return render_template(
        "client/reservation_success.html",
        settings=settings,
        order_number=number,
    )


@bp.get("/api/offerings")
@limiter.limit("60 per minute")
def api_offerings():
    body_type = (request.args.get("body_type") or "").strip()
    if body_type not in _VALID_BODY_TYPES:
        return jsonify({"error": "invalid_body_type"}), 400
    return jsonify(list_offerings_for_body_type(body_type))


@bp.get("/api/slots")
@limiter.limit("60 per minute")
def api_slots():
    body_type = (request.args.get("body_type") or "").strip()
    if body_type not in _VALID_BODY_TYPES:
        return jsonify({"error": "invalid_body_type"}), 400

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
        return jsonify({"error": "invalid_date"}), 400

    slots, err_key = list_slots_for_selection(
        body_type=body_type,
        service_ids=service_ids,
        package_id=package_id,
        day=day,
    )
    if err_key:
        return jsonify({"error": err_key}), 400
    return jsonify({"slots": slots or [], "date": day_raw})
