import argparse
import json
import logging
import os
import random
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any
from notifier import EmailChannel, Notifier, TelegramChannel


import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename=BASE_DIR / "notifier.log",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://api.giga.chat/v1/chat/completions"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY_RANGE = (3.0, 10.0)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class AnalyzerError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    db_path: Path
    days: int
    prompt_path: Path
    gigachat_credentials: str
    gigachat_scope: str
    gigachat_model: str
    gigachat_verify_ssl: bool
    gigachat_top_p: float
    gigachat_temperature: float
    gigachat_max_tokens: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_sender: str
    smtp_subject: str
    smtp_use_tls: bool
    email_recipient: str
    telegram_bot_token: str
    telegram_chat_id: str



def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc
    if value < 1:
        raise ValueError(f"{name} должен быть больше нуля")
    return value


def bounded_float(name: str, default: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} должен быть числом") from exc
    if not isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"{name} должен быть числом от 0 до {maximum}")
    return value


def boolean(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} должен быть true или false")
    return value in {"true", "1", "yes"}


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings(
        db_path=project_path(os.getenv("DB_PATH", "db.sqlite3")),
        days=positive_int("ANALYSIS_DAYS", 7),
        prompt_path=project_path(os.getenv("PROMPT_PATH", "PROMPT.md")),
        gigachat_credentials=os.getenv("GIGACHAT_CREDENTIALS", ""),
        gigachat_scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
        gigachat_model=os.getenv("GIGACHAT_MODEL", "GigaChat"),
        gigachat_verify_ssl=boolean("GIGACHAT_VERIFY_SSL", True),
        gigachat_top_p=bounded_float("GIGACHAT_TOP_P", 0.1, 1.0),
        gigachat_temperature=bounded_float("GIGACHAT_TEMPERATURE", 0.3, 2.0),
        gigachat_max_tokens=positive_int("GIGACHAT_MAX_TOKENS", 4000),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=positive_int("SMTP_PORT", 587),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_sender=os.getenv("SMTP_SENDER", ""),
        smtp_subject=os.getenv("SMTP_SUBJECT", "Уведомление"),
        smtp_use_tls=boolean("SMTP_USE_TLS", True),
        email_recipient=os.getenv("EMAIL_RECIPIENT", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


def notify_with_retry(
    name: str, message: str, notifier: Notifier, recipient: str
) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        failures = notifier.notify_all(message, recipient)
        if not failures:
            logger.info("%s: уведомление отправлено", name)
            return
        logger.warning(
            "%s: не удалось отправить (попытка %d/%d)",
            name,
            attempt,
            MAX_RETRIES,
        )
        if attempt < MAX_RETRIES:
            logger.info("%s: повтор через %d секунд", name, RETRY_DELAY_RANGE[0])
            time.sleep(RETRY_DELAY_RANGE[0])
    logger.error("%s: отправка не удалась после %d попыток", name, MAX_RETRIES)

def load_dialogues(
    settings: Settings, now: datetime
) -> tuple[list[dict[str, Any]], datetime]:
    since = now - timedelta(days=settings.days)
    query = """
        SELECT id, chat_id, type, text, created_at
        FROM bot_users_messages
        WHERE created_at >= ?
        ORDER BY created_at, id
    """
    with closing(
        sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
    ) as connection:
        rows = connection.execute(
            query, (since.strftime("%Y-%m-%d %H:%M:%S"),)
        ).fetchall()

    dialogues: dict[Any, dict[str, Any]] = {}
    for _, chat_id, sender, text, created_at in rows:
        role = sender.lower()
        if role not in {"human", "ai"}:
            raise ValueError(f"Неизвестный тип отправителя: {sender}")
        dialogue = dialogues.setdefault(chat_id, {"chat_id": chat_id, "messages": []})
        dialogue["messages"].append(
            {"created_at": created_at, "role": role, "text": text}
        )
    return list(dialogues.values()), since


def post_with_retry(
    url: str, operation: str, verify_ssl: bool, **kwargs: Any
) -> requests.Response:
    for attempt in range(MAX_RETRIES + 1):
        response = requests.post(
            url, verify=verify_ssl, timeout=REQUEST_TIMEOUT, **kwargs
        )
        logger.info(
            "%s: попытка %d/%d, HTTP %d",
            operation,
            attempt + 1,
            MAX_RETRIES + 1,
            response.status_code,
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt == MAX_RETRIES:
            return response
        delay = random.uniform(*RETRY_DELAY_RANGE)
        logger.warning(
            "%s: повтор запроса через %.1f секунды", operation, delay
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def get_access_token(settings: Settings) -> str:
    logger.info("Получение токена GigaChat")
    response = post_with_retry(
        GIGACHAT_AUTH_URL,
        "Получение токена",
        settings.gigachat_verify_ssl,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {settings.gigachat_credentials}",
        },
        data={"scope": settings.gigachat_scope},
    )
    if not response.ok:
        raise AnalyzerError(
            f"GigaChat OAuth: HTTP {response.status_code}: {response.text[:500]}"
        )
    token = response.json().get("access_token")
    if not token:
        raise AnalyzerError("GigaChat OAuth не вернул access_token")
    return token


def analyze_with_gigachat(
    system_prompt: str, dialogues: list[dict[str, Any]], settings: Settings
) -> str:
    if not settings.gigachat_credentials:
        raise ValueError("Укажите GIGACHAT_CREDENTIALS в .env")
    try:
        token = get_access_token(settings)
        logger.info("Отправка диалогов на анализ в GigaChat")
        response = post_with_retry(
            GIGACHAT_API_URL,
            "Анализ диалогов",
            settings.gigachat_verify_ssl,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": settings.gigachat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"dialogues": dialogues}, ensure_ascii=False
                        ),
                    },
                ],
                "top_p": settings.gigachat_top_p,
                "temperature": settings.gigachat_temperature,
                "max_tokens": settings.gigachat_max_tokens,
                "stream": False,
            },
        )
        if not response.ok:
            raise AnalyzerError(
                f"GigaChat API: HTTP {response.status_code}: {response.text[:500]}"
            )
        content = response.json()["choices"][0]["message"]["content"]
    except requests.RequestException as exc:
        raise AnalyzerError(f"Ошибка соединения с GigaChat API: {exc}") from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AnalyzerError("GigaChat API вернул неожиданную структуру ответа") from exc
    if not isinstance(content, str) or not content.strip():
        raise AnalyzerError("GigaChat вернул пустой ответ")
    return content.strip()


def empty_report() -> str:
    return """### 1. Общая статистика
- Количество проанализированных диалогов: 0
- Общее качество работы ИИ: за выбранный период диалоги отсутствуют, оценка не проводилась.

### 2. Проблемные ситуации и срывы
Диалоги за выбранный период отсутствуют.

### 3. Рекомендации для базы знаний (FAQ)
Рекомендации отсутствуют."""


def write_report(text: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
    temporary.replace(output)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Анализ диалогов Капитана Крылова и формирование Markdown-отчета"
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
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
        notify_with_retry("Email", report, email_notifier, settings.email_recipient)

        '''TELEGRAM_SETTINGS = {
            "bot_token": settings.telegram_bot_token,
        }
        telegram_notifier = Notifier().add_channel(TelegramChannel(**TELEGRAM_SETTINGS))
        notify_with_retry("Telegram", report, telegram_notifier, settings.telegram_chat_id)'''

    except (AnalyzerError, ValueError, OSError, sqlite3.Error) as exc:
        logger.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
