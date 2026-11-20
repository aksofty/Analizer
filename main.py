import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from config import load_settings, project_path
from dialogues import load_dialogues
from errors import AnalyzerError
from gigachat import analyze_with_gigachat
from logging_setup import configure_logging
from notifications import notify_with_retry
from notifier import CustomApiChannel, EmailChannel, Notifier, TelegramChannel
from report import empty_report, report_to_html

configure_logging(project_path("main.log"))
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Анализ диалогов Капитана Крылова и формирование Markdown-отчета"
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    try:
        settings = load_settings()
        now = datetime.now().astimezone()
        dialogues, _ = load_dialogues(settings, now)
        logger.info(
            "Загружено %d диалогов, %d сообщений",
            len(dialogues),
            sum(len(dialogue["messages"]) for dialogue in dialogues),
        )
        if dialogues:
            system_prompt = settings.prompt_path.read_text(encoding="utf-8")
            report = analyze_with_gigachat(system_prompt, dialogues, settings)
        else:
            logger.info("Диалоги за выбранный период отсутствуют, GigaChat не вызывается")
            report = empty_report()

        if settings.smtp_sender and settings.email_recipient:
            EMAIL_SETTINGS = {
                "host": settings.smtp_host,
                "port": settings.smtp_port,
                "username": settings.smtp_user,
                "password": settings.smtp_password,
                "sender": settings.smtp_sender,
                "subject": settings.smtp_subject,
                "use_tls": settings.smtp_use_tls,
                "html": True,
            }
            email_notifier = Notifier().add_channel(EmailChannel(**EMAIL_SETTINGS))
            notify_with_retry(
                "Email",
                report_to_html(report),
                email_notifier,
                settings.email_recipient,
            )

        if settings.telegram_bot_token and settings.telegram_chat_id:
            TELEGRAM_SETTINGS = {
                "bot_token": settings.telegram_bot_token,
            }
            telegram_notifier = Notifier().add_channel(
                TelegramChannel(**TELEGRAM_SETTINGS)
            )
            notify_with_retry(
                "Telegram",
                report,
                telegram_notifier,
                settings.telegram_chat_id,
            )

        if settings.custom_api_url and settings.custom_api_token:
            CustomApiChannel().send(
                data={
                    "recipient_user_id": settings.custom_api_recipient_id,
                    "sender_user_id": settings.custom_api_sender_id,
                    "message": report_to_html(report),
                }
            )

    except (AnalyzerError, ValueError, OSError, sqlite3.Error) as exc:
        logger.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
