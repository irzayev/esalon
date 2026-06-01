"""Validation and normalization for client phone, plates, dates."""
from __future__ import annotations

import re
from datetime import date, datetime

PHONE_RE = re.compile(r"^\+\d{10,15}$")
PLATE_RE = re.compile(r"^\d{2}[A-Z]{2}\d{3}$")


def normalize_phone(raw: str) -> str:
    s = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if not s:
        return ""
    if s.startswith("00"):
        s = "+" + s[2:]
    elif not s.startswith("+"):
        s = "+" + s.lstrip("0")
    return s


def combine_phone(dial_code: str, local: str) -> str:
    """Build E.164 number from country code (+994) and national digits (506003080)."""
    dial_digits = re.sub(r"\D", "", dial_code or "")
    local_digits = re.sub(r"\D", "", local or "")
    if not dial_digits and not local_digits:
        return ""
    if not dial_digits:
        return normalize_phone(local)
    if not local_digits:
        return ""
    while len(local_digits) > 1 and local_digits.startswith("0"):
        local_digits = local_digits[1:]
    return f"+{dial_digits}{local_digits}"


def parse_phone_form(form, *, default_dial: str = "+994") -> str:
    """Read phone from split dial/local fields or legacy single ``phone`` field."""
    local = (form.get("phone_local") or "").strip()
    dial = (form.get("phone_dial_code") or default_dial).strip()
    if local:
        return combine_phone(dial, local)
    return normalize_phone(form.get("phone") or "")


def validate_phone(phone: str) -> tuple[bool, str]:
    if not phone:
        return False, "Укажите телефон в международном формате"
    if not PHONE_RE.match(phone):
        return False, "Телефон: знак + и от 10 до 15 цифр"
    return True, ""


def normalize_plate(raw: str) -> str:
    return (raw or "").strip().upper().replace(" ", "").replace("-", "")


def validate_plate(plate: str) -> tuple[bool, str]:
    if not plate:
        return False, "Укажите госномер"
    if not PLATE_RE.match(plate):
        return False, "Госномер: формат XXBBXXX (2 цифры, 2 буквы, 3 цифры)"
    return True, ""


def format_birthday(value: date | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def parse_birthday(raw: str) -> tuple[date | None, str | None]:
    """Парсинг даты рождения dd/mm/yyyy. Пустая строка — OK (None)."""
    s = (raw or "").strip()
    if not s:
        return None, None
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date(), None
        except ValueError:
            continue
    return None, "Дата рождения: формат dd/mm/yyyy"
