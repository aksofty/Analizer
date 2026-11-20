import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from config import Settings


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
