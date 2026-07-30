from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

try:
    import structlog
except ModuleNotFoundError:
    structlog = None  # type: ignore[assignment]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "logger": record.name,
        }
        context = getattr(record, "structured_context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class BoundLogger:
    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self.logger = logger
        self.context = dict(context or {})

    def bind(self, **values: Any) -> BoundLogger:
        return BoundLogger(self.logger, {**self.context, **values})

    def _write(self, level: int, event: str, **values: Any) -> None:
        self.logger.log(level, event, extra={"structured_context": {**self.context, **values}})

    def debug(self, event: str, **values: Any) -> None:
        self._write(logging.DEBUG, event, **values)

    def info(self, event: str, **values: Any) -> None:
        self._write(logging.INFO, event, **values)

    def warning(self, event: str, **values: Any) -> None:
        self._write(logging.WARNING, event, **values)

    def error(self, event: str, **values: Any) -> None:
        self._write(logging.ERROR, event, **values)

    def exception(self, event: str, **values: Any) -> None:
        self.logger.exception(event, extra={"structured_context": {**self.context, **values}})


def get_logger(name: str = "kajovodagmar"):
    if structlog is not None:
        return structlog.get_logger(name)
    return BoundLogger(logging.getLogger(name))


def configure_logging(level: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(
        directory / "application.jsonl",
        maxBytes=5_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    if structlog is not None:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level.upper(), logging.INFO)
            ),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
