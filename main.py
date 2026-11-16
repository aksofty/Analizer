import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from html import escape
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
from notifier import EmailChannel, Notifier, TelegramChannel, CustomApiChannel

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

handler = RotatingFileHandler(
    "main.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[handler],
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
    custom_api_url: str
    custom_api_token: str
    custom_api_sender_id: str
    custom_api_recipient_id: str



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
        custom_api_url=os.getenv("CUSTOM_API_URL", ""),
        custom_api_token=os.getenv("CUSTOM_API_TOKEN", ""),
        custom_api_sender_id=os.getenv("CUSTOM_API_SENDER_ID", ""),
        custom_api_recipient_id=os.getenv("CUSTOM_API_RECIPIENT_ID", ""),
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


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    text = "".join(
        char
        for char in text
        if char in "\n\r\t" or not (ord(char) < 32 or ord(char) == 127)
    )
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def format_price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return clean_text(value)
    if not isfinite(number):
        return clean_text(value)
    text = f"{number:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


def parse_ai_payload(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    body = payload.get("text")
    if not isinstance(body, str):
        return None

    raw_offers = payload.get("offers")
    offers = (
        [offer for offer in raw_offers if isinstance(offer, dict)]
        if isinstance(raw_offers, list)
        else []
    )
    return clean_text(body), offers


def format_ai_text(text: Any) -> str:
    cleaned = clean_text(text)
    parsed = parse_ai_payload(cleaned)
    if parsed is None:
        return cleaned

    body, offers = parsed
    if not offers:
        return body

    lines = [body, "", "Найденные предложения:"]
    for index, offer in enumerate(offers, 1):
        title = clean_text(offer.get("title")) or "Без названия"
        price = format_price(offer.get("price"))
        line = f"{index}. {title}"
        if price:
            line += f" — {price} ₽"
        lines.append(line)

        description = clean_text(offer.get("description"))
        if description:
            lines.append(f"   {description}")

        url = clean_text(offer.get("url"))
        if url:
            lines.append(f"   {url}")

    return "\n".join(lines)


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
            {
                "created_at": created_at,
                "role": role,
                "text": format_ai_text(text) if role == "ai" else clean_text(text),
            }
        )
    return list(dialogues.values()), since


def post_with_retry(
    url: str, operation: str, verify_ssl: bool, **kwargs: Any
) -> requests.Response:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url, verify=verify_ssl, timeout=REQUEST_TIMEOUT, **kwargs
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == MAX_RETRIES:
                raise
            delay = random.uniform(*RETRY_DELAY_RANGE)
            logger.warning(
                "%s: %s, повтор через %.1f секунды", operation, exc, delay
            )
            time.sleep(delay)
            continue
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

        response_format =  {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                "oldest_message_date": {
                    "type": "string",
                    "description": "Дата самого старого сообщения"
                },
                "dialogs_count": {
                    "type": "integer",
                    "description": "Количество проанализированных диалогов"
                },
                "ai_quality": {
                    "type": "string",
                    "description": "Краткая оценка общего качества работы ИИ"
                },
                "issues": {
                    "type": "array",
                    "description": "Список проблемных ситуаций и срывов",
                    "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                        "type": "string",
                        "description": "Конкретное сообщение клиента"
                        },
                        "answer_json": {
                        "type": "string",
                        "description": "Оригинальный ответ консультанта одной строкой в формате JSON"
                        },
                        "problem": {
                        "type": "string",
                        "description": "Суть проблемы"
                        }
                    },
                    "required": ["question", "answer_json", "problem"]
                    }
                },
                "kb_recommendations": {
                    "type": "array",
                    "description": "Рекомендованные вопросы для добавления в базу знаний",
                    "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                        "type": "string",
                        "description": "Вопрос, который стоит добавить в базу знаний"
                        },
                        "reason": {
                        "type": "string",
                        "description": "Почему это важно добавить"
                        }
                    },
                    "required": ["question", "reason"]
                    }
                }
                },
                "required": [
                "oldest_message_date",
                "dialogs_count",
                "ai_quality",
                "issues",
                "kb_recommendations"
                ]
            }
        }


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
                "response_format": response_format
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


def html_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return escape(text, quote=False).replace("\n", "<br>")


def report_to_html(content: str | dict[str, Any]) -> str:
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Ответ GigaChat не является корректным JSON") from exc
    else:
        payload = content

    if not isinstance(payload, dict):
        raise ValueError("Ответ GigaChat должен быть JSON-объектом")

    parts = [
        f"<b>Дата первого сообщения:</b> "
        f"{html_text(payload.get('oldest_message_date')) or '—'}<br>",
        f"<b>Количество диалогов:</b> "
        f"{html_text(payload.get('dialogs_count')) or '—'}<br>",
        f"<b>Общее качество работы ИИ:</b> "
        f"{html_text(payload.get('ai_quality')) or '—'}<br>",
        "<br>",
        "<b>Проблемные ситуации и срывы</b><br>",
    ]

    issues = payload.get("issues")
    issues = issues if isinstance(issues, list) else []
    if issues:
        parts.append("<ul>")
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            parts.append(
                f"<li><b>Вопрос:</b> {html_text(issue.get('question'))}<br>"
                f"<b>Ответ:</b> <i>{html_text(issue.get('answer_json'))}</i><br>"
                f"<b>Проблема:</b> {html_text(issue.get('problem'))}</li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<i>Проблемных ситуаций не выявлено.</i><br>")

    parts.extend(["<br>", "<b>Рекомендации для базы знаний</b><br>"])
    recommendations = payload.get("kb_recommendations")
    recommendations = recommendations if isinstance(recommendations, list) else []
    if recommendations:
        parts.append("<ul>")
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            parts.append(
                f"<li><b>Вопрос:</b> {html_text(item.get('question'))}<br>"
                f"<b>Почему важно:</b> {html_text(item.get('reason'))}</li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<i>Рекомендации отсутствуют.</i><br>")

    return "".join(parts)


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
            notify_with_retry("Email", report_to_html(report), email_notifier, settings.email_recipient)

        '''if settings.telegram_bot_token and settings.telegram_chat_id:
            TELEGRAM_SETTINGS = {
                "bot_token": settings.telegram_bot_token,
            }
            telegram_notifier = Notifier().add_channel(TelegramChannel(**TELEGRAM_SETTINGS))
            notify_with_retry("Telegram", report, telegram_notifier, settings.telegram_chat_id)'''

        if settings.custom_api_url and settings.custom_api_token:
            CustomApiChannel().send(data={
                "recipient_user_id": settings.custom_api_recipient_id,
                "sender_user_id": settings.custom_api_sender_id,
                "message": report_to_html(report),
            })

    except (AnalyzerError, ValueError, OSError, sqlite3.Error) as exc:
        logger.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
