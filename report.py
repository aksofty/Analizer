import json
from html import escape
from pathlib import Path
from typing import Any


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
                f"<b>Ответ:</b> {html_text(item.get('answer'))}<br>"
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
