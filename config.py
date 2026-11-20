import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY_RANGE = (3.0, 10.0)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


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


@dataclass(frozen=True)
class Settings:
    db_path: Path
    days: int
    prompt_path: Path
    response_format_path: Path
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


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings(
        db_path=project_path(os.getenv("DB_PATH", "db.sqlite3")),
        days=positive_int("ANALYSIS_DAYS", 7),
        prompt_path=project_path(os.getenv("PROMPT_PATH", "PROMPT.md")),
        response_format_path=project_path(
            os.getenv("RESPONSE_FORMAT_PATH", "response_format.json")
        ),
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
