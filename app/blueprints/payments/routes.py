"""Payment gateway: Azericard callbacks and public pay links."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import csrf
from ...models.azericard import AzericardIntentStatus
from ...models.order import Order
from ...services.azericard import AzericardService

bp = Blueprint("payments", __name__)


@bp.route("/pay/<token>")
@csrf.exempt
def pay_checkout(token: str):
    """Публичная ссылка: клиент переходит на MPI без входа в CRM."""
    intent = AzericardService.get_intent_by_token(token)
    if not intent:
        abort(404)

    if intent.status == AzericardIntentStatus.COMPLETED:
        return redirect(url_for("payments.pay_result", token=token, status="ok"))

    if intent.status == AzericardIntentStatus.FAILED:
        return render_template(
            "payments/pay_unavailable.html",
            reason="failed",
        )

    az = AzericardService()
    if not az.enabled:
        return render_template("payments/pay_unavailable.html", reason="disabled")

    order = intent.business_order
    desc = f"Order #{order.number}" if order else f"Pay {intent.order}"
    back_ref = url_for("payments.azericard_backref", _external=True)
    try:
        checkout = az.launch_mpi_checkout(intent, description=desc, back_ref_url=back_ref)
    except ValueError:
        return redirect(url_for("payments.pay_result", token=token, status="ok"))

    return render_template(
        "orders/azericard_redirect.html",
        gateway=checkout.gateway_url,
        payload=checkout.form_fields,
    )


@bp.route("/pay/<token>/result")
@csrf.exempt
def pay_result(token: str):
    """Страница для клиента после возврата с банка."""
    intent = AzericardService.get_intent_by_token(token)
    status = request.args.get("status", "")
    order_number = ""
    if intent and intent.business_order:
        order_number = intent.business_order.number or ""
    return render_template(
        "payments/pay_result.html",
        status=status,
        order_number=order_number,
    )


@bp.route("/azericard/backref", methods=["GET", "POST"])
@csrf.exempt
def azericard_backref():
    """MPI callback: verify P_SIGN, finalize pending Payment."""
    data = request.form if request.method == "POST" else request.args
    fields = {k.upper(): v for k, v in data.items()}

    az = AzericardService()
    intent, err = az.process_backref(fields)

    if not intent:
        return err or "bad request", 400 if err == "bad request" else 404

    token = intent.pay_token or ""
    status = "fail" if err or intent.status != AzericardIntentStatus.COMPLETED else "ok"

    if current_user.is_authenticated:
        order = intent.business_order
        if err:
            flash("Оплата Azericard не подтверждена (ошибка проверки).", "error")
        elif intent.status == AzericardIntentStatus.COMPLETED:
            flash("Оплата Azericard успешно принята.", "success")
        else:
            flash("Оплата Azericard не завершена.", "warning")
        if order and order.number:
            return redirect(url_for("orders.detail", number=order.number))
        abort(404)

    if token:
        return redirect(url_for("payments.pay_result", token=token, status=status))
    return render_template("payments/pay_result.html", status=status, order_number="")
