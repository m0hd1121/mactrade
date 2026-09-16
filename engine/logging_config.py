"""Structured logging setup.

Every signal, rejection, order, connection event and error is logged to a
rotating file AND persisted to SQLite (see db/database.py) so the UI can
query history without re-parsing log files. Never logs credentials.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

_SECRET_PATTERN = re.compile(r"(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+", re.IGNORECASE)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and _SECRET_PATTERN.search(record.msg):
            record.msg = _SECRET_PATTERN.sub(r"\1=***REDACTED***", record.msg)
        return True


def configure_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fts")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fts.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(RedactSecretsFilter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.addFilter(RedactSecretsFilter())
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"fts.{name}")
