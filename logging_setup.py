import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_path: Path) -> None:
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler],
    )
