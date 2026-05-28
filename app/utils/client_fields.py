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
