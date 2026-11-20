import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY_RANGE,
    RETRYABLE_STATUSES,
    Settings,
)
from errors import AnalyzerError

logger = logging.getLogger(__name__)

GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://api.giga.chat/v1/chat/completions"


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


def load_response_format(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        logger.info(
            "Файл response_format не найден: %s, запрос пойдёт без него",
            path,
        )
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalyzerError(
            f"Не удалось прочитать response_format {path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise AnalyzerError(f"{path}: ожидается JSON-объект")

    if payload.get("type") != "json_schema" or not isinstance(
        payload.get("schema"), dict
    ):
        raise AnalyzerError(
            f"{path}: ожидается объект с type=json_schema и schema"
        )

    return payload


def append_response_format(
    system_prompt: str, response_format: dict[str, Any] | None
) -> str:
    if response_format is None:
        return system_prompt

    formatted = json.dumps(response_format, ensure_ascii=False, indent=2)
    return (
        f"{system_prompt.rstrip()}\n\n"
        "# Формат ответа\n"
        "Верни валидный JSON:\n"
        f"{formatted}"
    )


def analyze_with_gigachat(
    system_prompt: str, dialogues: list[dict[str, Any]], settings: Settings
) -> str:
    if not settings.gigachat_credentials:
        raise ValueError("Укажите GIGACHAT_CREDENTIALS в .env")
    try:
        token = get_access_token(settings)
        logger.info("Отправка диалогов на анализ в GigaChat")

        response_format = load_response_format(settings.response_format_path)
        system_prompt = append_response_format(system_prompt, response_format)

        request_body: dict[str, Any] = {
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
        }

        if response_format is not None:
            request_body["response_format"] = response_format

        response = post_with_retry(
            GIGACHAT_API_URL,
            "Анализ диалогов",
            settings.gigachat_verify_ssl,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=request_body,
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
