import os

import requests

from .base import NotificationChannel, NotificationError

TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramChannel(NotificationChannel):
    def __init__(self, bot_token: str | None = None, timeout: int = 30) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.timeout = timeout

    def send(self, message: str, recipient: str) -> None:
        if not self.bot_token:
            raise NotificationError("Не задан bot_token Telegram")

        url = f"{TELEGRAM_API_URL}/bot{self.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": recipient, "text": message},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NotificationError(f"Ошибка соединения с Telegram API: {exc}") from exc

        if not response.ok:
            try:
                description = response.json().get("description", response.text[:500])
            except ValueError:
                description = response.text[:500]
            raise NotificationError(
                f"Telegram API: HTTP {response.status_code}: {description}"
            )
