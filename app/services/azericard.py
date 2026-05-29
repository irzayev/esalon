"""Azericard 3DSecure MPI integration (E-Commerce CGI Link).

Совместимо с контрактом eMTK / документацией Azericard:
RSA-SHA256 P_SIGN, уникальный ORDER, callback BACKREF с верификацией подписи.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.azericard import (
    AzericardIntentStatus,
    AzericardLog,
    AzericardPaymentIntent,
)
from ..models.payment import Payment, PaymentStatus
from ..models.settings import Settings

AZC_SANDBOX_MPI = "https://testmpi.3dsecure.az/cgi-bin/cgi_link"
AZC_PRODUCTION_MPI = "https://mpi.3dsecure.az/cgi-bin/cgi_link"

# §2.2.1 E-Commerce (browser redirect, TRTYPE=1)
AZC_MAC_AUTH_ORDER = ("AMOUNT", "CURRENCY", "TERMINAL", "TRTYPE", "TIMESTAMP", "NONCE", "MERCH_URL")
# Callback P_SIGN verification (provider contract)
AZC_MAC_CALLBACK_ORDER = ("AMOUNT", "TERMINAL", "APPROVAL", "RRN", "INT_REF")


@dataclass
class AzericardCheckout:
    """Prepared redirect to MPI gateway."""

    gateway_url: str
    form_fields: dict[str, str]
    intent: AzericardPaymentIntent


class AzericardService:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings.get()

    @property
    def enabled(self) -> bool:
        return bool(
            self.s.azericard_enabled
            and self.s.azericard_terminal_id
            and self.s.azericard_merchant_name
            and self.s.azericard_merchant_url
            and self._private_key_pem()
        )

    def _private_key_pem(self) -> str:
        return (self.s.azericard_private_key_pem or self.s.azericard_secret_key or "").strip()

    def gateway_url(self) -> str:
        if self.s.azericard_gateway_url:
            return self.s.azericard_gateway_url.strip()
        return AZC_SANDBOX_MPI if self.s.azericard_test_mode else AZC_PRODUCTION_MPI

    def create_payment_link(
        self,
        *,
        payment: Payment,
        business_order_id: int,
        amount: float,
    ) -> AzericardPaymentIntent:
        """Создать pending-платёж и токен публичной ссылки (MPI — при открытии клиентом)."""
        order_id = self._new_order(self.s.azericard_terminal_id or "00000000")
        intent = AzericardPaymentIntent(
            order=order_id,
            pay_token=secrets.token_urlsafe(32),
            payment_id=payment.id,
            order_id=business_order_id,
            amount=amount,
            currency=self.s.azericard_currency or "944",
            status=AzericardIntentStatus.CREATED,
            terminal=self.s.azericard_terminal_id,
        )
        db.session.add(intent)
        db.session.commit()
        self._log(
            event="pay_link_created",
            direction="out",
            order=intent.order,
            payment_id=payment.id,
            order_id=business_order_id,
            note=f"token amount={float(amount):.2f}",
        )
        return intent

    def launch_mpi_checkout(
        self,
        intent: AzericardPaymentIntent,
        *,
        description: str,
        back_ref_url: str,
    ) -> AzericardCheckout:
        """Собрать подписанную форму и перенаправить на MPI (открытие ссылки клиентом)."""
        if intent.status == AzericardIntentStatus.COMPLETED:
            raise ValueError("already_paid")

        nonce = _azc_nonce()
        timestamp = _azc_timestamp()
        amount_str = f"{float(intent.amount):.2f}"
        form: dict[str, str] = {
            "AMOUNT": amount_str,
            "CURRENCY": intent.currency,
            "ORDER": intent.order,
            "DESC": (description or "")[:50],
            "MERCH_NAME": (self.s.azericard_merchant_name or "")[:50],
            "MERCH_URL": (self.s.azericard_merchant_url or "")[:250],
            "TERMINAL": self.s.azericard_terminal_id or "",
            "EMAIL": (self.s.azericard_email or "")[:80],
            "TRTYPE": "1",
            "COUNTRY": (self.s.azericard_country or "AZ")[:2],
            "MERCH_GMT": self.s.azericard_merch_gmt or "+4",
            "BACKREF": back_ref_url,
            "TIMESTAMP": timestamp,
            "NONCE": nonce,
            "LANG": "RU",
        }
        pem = self._private_key_pem()
        if pem:
            form["P_SIGN"] = _azc_sign(form, AZC_MAC_AUTH_ORDER, pem)

        intent.nonce = nonce
        intent.status = AzericardIntentStatus.REDIRECTED
        db.session.commit()

        self._log(
            event="mpi_request",
            direction="out",
            order=intent.order,
            payment_id=intent.payment_id,
            order_id=intent.order_id,
            note=f"E-Commerce TRTYPE=1 amount={amount_str}",
            raw=_form_log_body(form),
        )
        return AzericardCheckout(
            gateway_url=self.gateway_url(),
            form_fields=form,
            intent=intent,
        )

    @staticmethod
    def get_intent_by_token(token: str) -> AzericardPaymentIntent | None:
        if not token:
            return None
        return AzericardPaymentIntent.query.filter_by(pay_token=token.strip()).first()

    def log_link_open(self, intent: AzericardPaymentIntent) -> None:
        """Diagnostic: record that the public pay link was opened and its current status."""
        self._log(
            event="pay_link_opened",
            direction="in",
            order=intent.order,
            payment_id=intent.payment_id,
            order_id=intent.order_id,
            rc=intent.rc,
            note=f"status={intent.status} enabled={self.enabled}",
        )

    def process_backref(self, fields: dict) -> tuple[AzericardPaymentIntent | None, str | None]:
        """Verify callback, finalize Payment. Returns (intent, error_message)."""
        order = fields.get("ORDER")
        self._log(
            event="backref",
            direction="in",
            order=order,
            rc=fields.get("RC"),
            note=f"ACTION={fields.get('ACTION')} APPROVAL={fields.get('APPROVAL')} RRN={fields.get('RRN')}",
            raw=_form_log_body(fields),
        )
        if not order:
            return None, "bad request"

        intent = AzericardPaymentIntent.query.filter_by(order=order).first()
        if not intent:
            self._log(event="backref_unknown", direction="in", order=order, note="intent not found")
            return None, "unknown order"

        pub = (self.s.azericard_public_key_pem or "").strip()
        provided_sign = fields.get("P_SIGN") or ""
        if pub:
            if not _azc_verify(fields, AZC_MAC_CALLBACK_ORDER, provided_sign, pub):
                intent.status = AzericardIntentStatus.FAILED
                intent.note = "P_SIGN verify failed"
                db.session.commit()
                self._log(
                    event="verify_fail",
                    direction="in",
                    order=order,
                    payment_id=intent.payment_id,
                    order_id=intent.order_id,
                    note="callback P_SIGN mismatch",
                )
                return intent, "invalid signature"
        else:
            self._log(
                event="verify_skipped",
                direction="in",
                order=order,
                payment_id=intent.payment_id,
                order_id=intent.order_id,
                note="public key missing",
            )

        try:
            callback_amount = Decimal(str(fields.get("AMOUNT") or "0")).quantize(Decimal("0.01"))
            intent_amount = Decimal(str(intent.amount)).quantize(Decimal("0.01"))
        except Exception:
            callback_amount = Decimal("0")
            intent_amount = Decimal("0")
        if callback_amount != intent_amount:
            intent.status = AzericardIntentStatus.FAILED
            intent.note = f"amount mismatch: cb={callback_amount} vs intent={intent.amount}"
            db.session.commit()
            self._log(
                event="amount_mismatch",
                direction="in",
                order=order,
                payment_id=intent.payment_id,
                order_id=intent.order_id,
                note=intent.note,
            )
            return intent, "amount mismatch"

        self._finalize_intent(
            intent,
            rc=fields.get("RC"),
            action=fields.get("ACTION"),
            approval=fields.get("APPROVAL"),
            rrn=fields.get("RRN"),
            int_ref=fields.get("INT_REF"),
            raw_fields=fields,
        )
        return intent, None

    def _finalize_intent(
        self,
        intent: AzericardPaymentIntent,
        *,
        rc: Optional[str],
        action: Optional[str],
        approval: Optional[str],
        rrn: Optional[str],
        int_ref: Optional[str],
        raw_fields: dict,
    ) -> Payment | None:
        intent.rc = (rc or "")[:8] or None
        intent.action = (action or "")[:4] or None
        intent.approval = (approval or "")[:12] or None
        intent.rrn = (rrn or "")[:16] or None
        intent.int_ref = (int_ref or "")[:40] or None

        payment = db.session.get(Payment, intent.payment_id)
        if not payment:
            intent.status = AzericardIntentStatus.FAILED
            intent.note = "payment row missing"
            db.session.commit()
            return None

        if intent.status == AzericardIntentStatus.COMPLETED and payment.status == PaymentStatus.SUCCESS:
            db.session.commit()
            return payment

        payment.raw_response = json.dumps(raw_fields, ensure_ascii=False)
        is_approved = (intent.action or "") == "0" and (intent.rc or "") == "00"
        if not is_approved:
            intent.status = AzericardIntentStatus.FAILED
            payment.status = PaymentStatus.FAILED
            if rrn:
                payment.transaction_reference = rrn
            db.session.commit()
            return None

        payment.status = PaymentStatus.SUCCESS
        payment.transaction_reference = rrn or payment.transaction_reference
        intent.status = AzericardIntentStatus.COMPLETED
        db.session.commit()

        from .order_payments import apply_cashback_if_order_paid

        apply_cashback_if_order_paid(payment.order_id)
        return payment

    def _new_order(self, terminal: str) -> str:
        now = datetime.now(timezone.utc)
        prefix = now.strftime("%y%m%d")
        for _ in range(10):
            trace = f"{secrets.randbelow(1_000_000):06d}"
            candidate = f"{prefix}{trace}"
            if not AzericardPaymentIntent.query.filter_by(order=candidate).first():
                return candidate
        return f"{prefix}{secrets.randbelow(1_000_000):06d}{secrets.randbelow(100):02d}"

    def _log(self, **kwargs) -> None:
        try:
            raw = kwargs.pop("raw", None)
            if raw and len(raw) > 8000:
                raw = raw[:8000] + "… [truncated]"
            db.session.add(
                AzericardLog(
                    direction=kwargs.pop("direction", "out"),
                    event=kwargs.pop("event", "")[:48],
                    order=kwargs.pop("order", None),
                    payment_id=kwargs.pop("payment_id", None),
                    order_id=kwargs.pop("order_id", None),
                    http_status=kwargs.pop("http_status", None),
                    rc=kwargs.pop("rc", None),
                    note=(kwargs.pop("note", None) or "")[:500] or None,
                    raw_body=raw,
                )
            )
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()


def _azc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _azc_nonce() -> str:
    return secrets.token_hex(16)


def _azc_mac_source(fields: dict, order: tuple[str, ...]) -> bytes:
    parts = []
    for name in order:
        val = fields.get(name)
        if val is None or val == "":
            parts.append("-")
            continue
        s = str(val)
        parts.append(f"{len(s)}{s}")
    return "".join(parts).encode("utf-8")


def _azc_sign(fields: dict, order: tuple[str, ...], private_key_pem: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    src = _azc_mac_source(fields, order)
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = key.sign(src, padding.PKCS1v15(), hashes.SHA256())
    return signature.hex().upper()


def _azc_verify(fields: dict, order: tuple[str, ...], signature_hex: str, public_key_pem: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        src = _azc_mac_source(fields, order)
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        sig = bytes.fromhex((signature_hex or "").strip())
        key.verify(sig, src, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _azc_mask_secret(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}…{v[-4:]}"


def _azc_mask_form(data: dict) -> dict:
    redacted = {}
    for k, v in data.items():
        key = (k or "").upper()
        if key == "CARD":
            digits = re.sub(r"\D", "", str(v or ""))
            redacted[k] = digits[:6] + "*" * max(0, len(digits) - 10) + digits[-4:] if len(digits) >= 10 else "****"
        elif key in ("CVC2", "CVC2_RC", "TAVV", "EXT_MPI_ECI", "P_SIGN"):
            redacted[k] = _azc_mask_secret(str(v) if v is not None else "")
        else:
            redacted[k] = v
    return redacted


def _form_log_body(form: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in _azc_mask_form(form).items())
