"""Country calling codes for international phone inputs."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_DIAL_CODE = "+994"

_FALLBACK = [
    {"iso": "AZ", "name": "Azerbaijan", "dial": "+994"},
]

_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "static" / "json" / "country_dial_codes.json"
)


@lru_cache(maxsize=1)
def get_country_dial_codes() -> list[dict[str, str]]:
    try:
        with _DATA_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if data else _FALLBACK
    except (OSError, json.JSONDecodeError):
        return list(_FALLBACK)
