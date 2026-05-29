"""Singleton row of application settings, fully editable from admin panel."""
from datetime import datetime
from pathlib import Path

from ..config import UPLOAD_DIR
from ..extensions import db


class Settings(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)

    # --- Branding (чеки, WhatsApp, UI) ---
    company_name = db.Column(db.String(160), default="Washer CRM")
    company_tagline = db.Column(db.String(160), default="")  # подпись под названием в меню
    company_address = db.Column(db.String(255), default="")
    company_phone = db.Column(db.String(40), default="")
    company_email = db.Column(db.String(160), default="")
    company_website = db.Column(db.String(255), default="")
    company_waze = db.Column(db.String(512), default="")  # ссылка Waze для WhatsApp {waze}
    company_logo = db.Column(db.String(255))
    company_tax_id = db.Column(db.String(40), default="")  # VÖEN
    wa_template_ready = db.Column(db.Text, default="")
    wa_template_booking = db.Column(db.Text, default="")
    wa_template_reminder = db.Column(db.Text, default="")
    wa_template_payment = db.Column(db.Text, default="")
    default_language = db.Column(db.String(5), default="az")
    default_currency = db.Column(db.String(8), default="AZN")
    timezone = db.Column(db.String(40), default="Asia/Baku")

    # --- Finance ---
    vat_enabled = db.Column(db.Boolean, default=False)  # legacy; kept in sync with VAT mode
    vat_rate = db.Column(db.Float, default=18.0)  # AZ default 18%
    vat_included_in_price = db.Column(db.Boolean, default=True)

    @property
    def vat_add_on_top(self) -> bool:
        """True: НДС начисляется сверху; False: НДС уже в ценах услуг."""
        return bool(self.vat_enabled and not self.vat_included_in_price)

    def set_vat_mode(self, add_on_top: bool) -> None:
        self.vat_enabled = True
        self.vat_included_in_price = not add_on_top

    # --- Bonus program ---
    bonus_cashback_percent = db.Column(db.Float, default=5.0)
    bonus_max_percent_of_order = db.Column(db.Float, default=30.0)
    bonus_enabled = db.Column(db.Boolean, default=True)
    bonus_level_silver_threshold = db.Column(db.Float, default=500.0)
    bonus_level_gold_threshold = db.Column(db.Float, default=2000.0)
    bonus_level_platinum_threshold = db.Column(db.Float, default=5000.0)

    # --- Azericard integration ---
    azericard_enabled = db.Column(db.Boolean, default=False)
    azericard_merchant_id = db.Column(db.String(64), default="")
    azericard_terminal_id = db.Column(db.String(64), default="")
    azericard_merchant_name = db.Column(db.String(160), default="")
    azericard_merchant_url = db.Column(db.String(255), default="")
    azericard_email = db.Column(db.String(80), default="")
    azericard_merch_gmt = db.Column(db.String(5), default="+4")
    azericard_secret_key = db.Column(db.Text, default="")  # legacy; use private_key_pem
    azericard_private_key_pem = db.Column(db.Text, default="")
    azericard_public_key_pem = db.Column(db.Text, default="")
    azericard_gateway_url = db.Column(
        db.String(255),
        default="https://testmpi.3dsecure.az/cgi-bin/cgi_link",
    )
    azericard_currency = db.Column(db.String(8), default="944")  # AZN ISO
    azericard_country = db.Column(db.String(4), default="AZ")
    azericard_test_mode = db.Column(db.Boolean, default=True)

    # --- Evolution API (WhatsApp) ---
    evolution_enabled = db.Column(db.Boolean, default=False)
    evolution_base_url = db.Column(db.String(255), default="")
    evolution_api_key = db.Column(db.String(255), default="")
    evolution_instance_name = db.Column(db.String(120), default="")
    evolution_default_country_code = db.Column(db.String(8), default="994")
    evolution_send_on_booking = db.Column(db.Boolean, default=True)
    evolution_send_on_ready = db.Column(db.Boolean, default=True)
    evolution_send_reminders = db.Column(db.Boolean, default=True)
    evolution_reminder_days = db.Column(db.Integer, default=30)

    # --- Receipt template ---
    receipt_template = db.Column(db.Text, default="")
    receipt_cashier_name = db.Column(db.String(120), default="")
    receipt_footer_note = db.Column(db.String(500), default="")

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls) -> "Settings":
        inst = cls.query.first()
        if not inst:
            inst = cls()
            db.session.add(inst)
            db.session.commit()
        return inst

    def logo_url(self) -> str | None:
        if not self.company_logo:
            return None
        return f"/static/uploads/{self.company_logo}"

    def logo_path(self) -> Path | None:
        if not self.company_logo:
            return None
        path = UPLOAD_DIR / self.company_logo
        return path if path.is_file() else None

    def contact_block(self, separator: str = "\n") -> str:
        """Текст контактов для чеков и WhatsApp."""
        lines: list[str] = []
        if self.company_phone:
            lines.append(f"Tel: {self.company_phone}")
        if self.company_email:
            lines.append(f"Email: {self.company_email}")
        if self.company_website:
            lines.append(self.company_website)
        if self.company_address:
            lines.append(self.company_address)
        return separator.join(lines)

    def contact_line_inline(self) -> str:
        """Одна строка контактов для PDF."""
        parts = [p for p in [self.company_phone, self.company_email] if p]
        return " · ".join(parts)
