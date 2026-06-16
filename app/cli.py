"""Flask CLI commands."""
import click
from flask import Flask

from .services.whatsapp_messages import send_reminders
from .services.wa_inbox import purge_expired_messages


def register_cli(app: Flask) -> None:
    @app.cli.command("wa-reminders")
    @click.option("--dry-run", is_flag=True, help="Показать, кому уйдут сообщения, без отправки")
    def wa_reminders(dry_run: bool) -> None:
        """Отправить напоминания «пора на салон» (для cron)."""
        result = send_reminders(dry_run=dry_run)
        click.echo(
            f"due={result.get('due', 0)} sent={result.get('sent', 0)} "
            f"failed={result.get('failed', 0)}"
            + (f" reason={result['reason']}" if result.get("reason") else "")
            + (" (dry-run)" if dry_run else "")
        )

    @app.cli.command("wa-purge-messages")
    def wa_purge_messages() -> None:
        """Удалить WhatsApp-сообщения старше срока хранения из настроек чат-бота."""
        deleted = purge_expired_messages()
        click.echo(f"deleted={deleted}")
