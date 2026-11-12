# Notifier

Пакет для отправки сообщений в несколько каналов уведомлений.

## Состав

```
notifier/
├── __init__.py      # экспорт публичных классов
├── base.py          # интерфейс NotificationChannel и NotificationError
├── email.py         # EmailChannel (SMTP)
├── telegram.py      # TelegramChannel (Telegram Bot API)
└── notifier.py      # Notifier — менеджер каналов
```

## Установка

Зависимости уже указаны в корневом `requirements.txt`:

```bash
pip install -r requirements.txt
```

Для Telegram используется `requests`.

## Быстрый старт

```python
from notifier import Notifier, EmailChannel, TelegramChannel

notifier = (
    Notifier()
    .add_channel(EmailChannel(
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password="secret",
        sender="bot@example.com",
    ))
    .add_channel(TelegramChannel(bot_token="123:ABC"))
)

notifier.notify_all(
    message="Ваш заказ успешно оформлен!",
    recipient="user_123",
)
```

`add_channel()` возвращает `self`, поэтому каналы можно подключать цепочкой.

## EmailChannel

Отправляет письмо через SMTP.

### Параметры конструктора

| Параметр   | Тип            | По умолчанию    | Описание                              |
|------------|----------------|-----------------|---------------------------------------|
| `host`     | `str \| None`  | `SMTP_HOST`     | SMTP-сервер                           |
| `port`     | `int \| None`  | `SMTP_PORT` / 587 | Порт SMTP                           |
| `username` | `str \| None`  | `SMTP_USER`     | Логин                                 |
| `password` | `str \| None`  | `SMTP_PASSWORD` | Пароль                                |
| `sender`   | `str \| None`  | `SMTP_SENDER` или `username` | Адрес отправителя      |
| `subject`  | `str`          | `"Уведомление"` | Тема письма                           |
| `use_tls`  | `bool`         | `True`          | Использовать STARTTLS                 |
| `timeout`  | `int`          | `30`            | Таймаут соединения, секунды           |

### Переменные окружения

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=secret
SMTP_SENDER=bot@example.com
```

### Пример

```python
from notifier import EmailChannel

channel = EmailChannel(subject="Отчет готов")
channel.send("Отчет сформирован.", "client@example.com")
```

## TelegramChannel

Отправляет сообщение через Telegram Bot API. Получатель — `chat_id`.

### Параметры конструктора

| Параметр    | Тип             | По умолчанию          | Описание                     |
|-------------|-----------------|-----------------------|------------------------------|
| `bot_token` | `str \| None`   | `TELEGRAM_BOT_TOKEN`  | Токен бота                   |
| `timeout`   | `int`           | `30`                  | Таймаут запроса, секунды     |

### Переменная окружения

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

### Пример

```python
from notifier import TelegramChannel

channel = TelegramChannel()
channel.send("Отчет сформирован.", "123456789")
```

## Notifier

Менеджер каналов.

| Метод | Описание |
|-------|----------|
| `add_channel(channel)` | Добавляет канал и возвращает `self` |
| `notify_all(message, recipient)` | Отправляет сообщение во все подключенные каналы |

Если канал завершился с ошибкой, она логируется через `logging`, а остальные каналы продолжают работу.

```python
import logging
from notifier import Notifier, EmailChannel, TelegramChannel

logging.basicConfig(level=logging.INFO)

Notifier().add_channel(TelegramChannel()).notify_all("Текст", "123456789")
```

## Свой канал

Унаследуйте `NotificationChannel` и реализуйте `send()`:

```python
from notifier import NotificationChannel


class ConsoleChannel(NotificationChannel):
    def send(self, message: str, recipient: str) -> None:
        print(f"[CONSOLE] {recipient}: {message}")


Notifier().add_channel(ConsoleChannel()).notify_all("Привет", "user_1")
```

При ошибке отправки рекомендуется выбрасывать `NotificationError` из `notifier.base`.
