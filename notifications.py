import logging
import time

from config import MAX_RETRIES, RETRY_DELAY_RANGE
from notifier import Notifier

logger = logging.getLogger(__name__)


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
