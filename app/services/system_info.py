"""Read-only system reference: public URLs and cron commands for admin settings."""
from __future__ import annotations

from flask import current_app, url_for

from ..config import PROJECT_ROOT


def _external_url(endpoint: str, **values) -> str:
    scheme = current_app.config.get("PREFERRED_URL_SCHEME", "https")
    return url_for(endpoint, _external=True, _scheme=scheme, **values)


def build_system_info() -> dict:
    """URLs and copy-ready cron / Flask CLI commands."""
    cron_secret = (current_app.config.get("CRON_SECRET") or "").strip()
    project_dir = str(PROJECT_ROOT)

    reservation_url = _external_url("client_reservation.index")
    track_url = _external_url("client_portal.index")

    flask_commands = [
        "flask wa-reminders",
        "flask wa-reminders --dry-run",
        "flask wa-purge-messages",
    ]

    flask_cron_lines = [
        f"0 9 * * * cd {project_dir} && FLASK_APP=wsgi.py flask wa-reminders",
        f"0 3 * * * cd {project_dir} && FLASK_APP=wsgi.py flask wa-purge-messages",
    ]

    http_cron_lines: list[str] = []
    if cron_secret:
        wa_reminders_url = _external_url("cron_wa_reminders", token=cron_secret)
        wa_purge_url = _external_url("cron_wa_purge_messages", token=cron_secret)
        http_cron_lines = [
            f'0 9 * * * curl -fsS "{wa_reminders_url}"',
            f'0 3 * * * curl -fsS "{wa_purge_url}"',
        ]
    else:
        wa_reminders_url = ""
        wa_purge_url = ""

    return {
        "reservation_url": reservation_url,
        "track_url": track_url,
        "cron_secret_set": bool(cron_secret),
        "flask_commands": flask_commands,
        "flask_cron": "\n".join(flask_cron_lines),
        "http_cron": "\n".join(http_cron_lines),
        "wa_reminders_url": wa_reminders_url,
        "wa_purge_url": wa_purge_url,
        "project_dir": project_dir,
    }
