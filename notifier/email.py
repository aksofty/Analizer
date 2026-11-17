import logging
import os
import smtplib
from email.message import EmailMessage

from .base import NotificationChannel, NotificationError

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        sender: str | None = None,
        subject: str = "Уведомление",
        use_tls: bool = True,
        html: bool = False,
        timeout: int = 30,
    ) -> None:
        self.host = host or os.getenv("SMTP_HOST", "")
        self.port = port if port is not None else int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USER", "")
        self.password = password if password is not None else os.getenv("SMTP_PASSWORD", "")
        self.sender = sender or os.getenv("SMTP_SENDER") or self.username
        self.subject = subject
        self.use_tls = use_tls
        self.html = html
        self.timeout = timeout

    def send(self, message: str, recipient: str) -> None:
        if not self.host:
            logger.error("Email: не задан SMTP_HOST")
            raise NotificationError("Не задан SMTP_HOST")
        if not self.sender:
            logger.error("Email: не задан адрес отправителя SMTP_SENDER")
            raise NotificationError("Не задан адрес отправителя SMTP_SENDER")

        logger.info(
            "Email: отправка сообщения на %s через %s:%d",
            recipient,
            self.host,
            self.port,
        )

        email = EmailMessage()
        email["From"] = self.sender
        email["To"] = recipient
        email["Subject"] = self.subject
        email.set_content(message, subtype="html" if self.html else "plain")

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("Email: не удалось отправить на %s: %s", recipient, exc)
            raise NotificationError(
                f"Не удалось отправить email на {recipient}: {exc}"
            ) from exc

        logger.info("Email: сообщение отправлено на %s", recipient)
