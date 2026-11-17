import logging
import os

import requests

from .base import NotificationChannel, NotificationError

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramChannel(NotificationChannel):
    def __init__(self, bot_token: str | None = None, timeout: int = 30) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.timeout = timeout

    def send(self, message: str, recipient: str) -> None:
        if not self.bot_token:
            logger.error("Telegram: не задан bot_token")
            raise NotificationError("Не задан bot_token Telegram")

        logger.info("Telegram: отправка сообщения получателю %s", recipient)

        url = f"{TELEGRAM_API_URL}/bot{self.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": recipient, "text": message},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error(
                "Telegram: ошибка соединения при отправке получателю %s: %s",
                recipient,
                exc,
            )
            raise NotificationError(f"Ошибка соединения с Telegram API: {exc}") from exc

        if not response.ok:
            try:
                description = response.json().get("description", response.text[:500])
            except ValueError:
                description = response.text[:500]
            logger.error(
                "Telegram: HTTP %d при отправке получателю %s: %s",
                response.status_code,
                recipient,
                description,
            )
            raise NotificationError(
                f"Telegram API: HTTP {response.status_code}: {description}"
            )

        logger.info("Telegram: сообщение отправлено получателю %s", recipient)
