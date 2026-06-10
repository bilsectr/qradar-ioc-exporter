"""Structured JSON logging to stdout and a rotating file.

The formatter intentionally never serialises QRadar tokens or API keys; only
the fields explicitly attached to a log record are emitted.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import UTC, datetime
from pathlib import Path

# Standard LogRecord attributes that should not be duplicated into the JSON
# "extra" payload.
_RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any structured extras (feed_type, entry_count, duration_ms...).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure root logging with JSON output to stdout and a rotating file."""
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if called more than once (e.g. uvicorn reload).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        root.warning("Could not open log file; logging to stdout only: %s", exc)

    # Align uvicorn's loggers with our handlers/format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
