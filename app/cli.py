"""Flask CLI commands."""
import click
from flask import Flask

from .services.whatsapp_messages import send_reminders


def register_cli(app: Flask) -> None:
    @app.cli.command("wa-reminders")
    @click.option("--dry-run", is_flag=True, help="Показать, кому уйдут сообщения, без отправки")
    def wa_reminders(dry_run: bool) -> None:
        """Отправить напоминания «пора на мойку» (для cron)."""
        result = send_reminders(dry_run=dry_run)
        click.echo(
            f"due={result.get('due', 0)} sent={result.get('sent', 0)} "
            f"failed={result.get('failed', 0)}"
            + (f" reason={result['reason']}" if result.get("reason") else "")
            + (" (dry-run)" if dry_run else "")
        )
