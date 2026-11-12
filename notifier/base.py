from abc import ABC, abstractmethod


class NotificationError(Exception):
    """Ошибка отправки уведомления через канал."""


class NotificationChannel(ABC):
    """Интерфейс канала отправки уведомлений."""

    @abstractmethod
    def send(self, message: str, recipient: str) -> None:
        """Отправляет сообщение получателю."""
