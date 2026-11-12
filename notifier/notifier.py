import logging

from .base import NotificationChannel

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self) -> None:
        self._channels: list[NotificationChannel] = []

    def add_channel(self, channel: NotificationChannel) -> "Notifier":
        self._channels.append(channel)
        return self

    def notify_all(self, message: str, recipient: str) -> list[Exception]:
        failures: list[Exception] = []
        for channel in self._channels:
            try:
                channel.send(message, recipient)
            except Exception as exc:
                logger.exception(
                    "Ошибка при отправке через %s", type(channel).__name__
                )
                failures.append(exc)
        return failures
