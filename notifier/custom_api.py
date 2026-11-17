import logging
import os
from typing import Any

import requests

from .base import NotificationChannel, NotificationError

logger = logging.getLogger(__name__)


class CustomApiChannel(NotificationChannel):
    def __init__(
        self,
        api_url: str | None = None,
        api_token: str | None = None,
        sender_user_id: str | int = "",
        timeout: int = 30,
    ) -> None:
        self.api_url = api_url or os.getenv("CUSTOM_API_URL", "")
        self.api_token = api_token or os.getenv("CUSTOM_API_TOKEN", "")
        self.sender_user_id = sender_user_id or os.getenv(
            "CUSTOM_API_SENDER_USER_ID", ""
        )
        self.timeout = timeout

    def send(
        self,
        message: str = "",
        recipient: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.api_url:
            logger.error("Custom API: не задан CUSTOM_API_URL")
            raise NotificationError("Не задан CUSTOM_API_URL")
        if not self.api_token:
            logger.error("Custom API: не задан CUSTOM_API_TOKEN")
            raise NotificationError("Не задан CUSTOM_API_TOKEN")

        logger.info(
            "Custom API: отправка сообщения (получатель: %s)",
            recipient or "из payload",
        )

        payload = (
            data
            if data is not None
            else {
                "recipient_user_id": recipient,
                "sender_user_id": self.sender_user_id,
                "message": message,
            }
        )

        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": (
                        "application/x-www-form-urlencoded; charset=utf-8"
                    ),
                },
                data=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("Custom API: ошибка соединения: %s", exc)
            raise NotificationError(
                f"Ошибка соединения с Custom API: {exc}"
            ) from exc

        if not response.ok:
            logger.error(
                "Custom API: HTTP %d: %s",
                response.status_code,
                response.text[:500],
            )
            raise NotificationError(
                f"Custom API: HTTP {response.status_code}: {response.text[:500]}"
            )

        logger.info("Custom API: сообщение отправлено")
