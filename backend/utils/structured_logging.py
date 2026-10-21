"""JSON logging configuration for backend application events."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from backend.check_setup import read_local_env


class JsonFormatter(logging.Formatter):
    """Serialize log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log_record"),
        }
        for field in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "error_type",
            "pages",
            "chunks",
            "changed_pages",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    """Configure the backend logger without logging request bodies, secrets, or exception text."""
    local_env = read_local_env()
    level_name = os.environ.get("LOG_LEVEL") or local_env.get("LOG_LEVEL", "INFO")
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise TypeError("LOG_LEVEL must be a valid Python logging level.")

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    backend_logger = logging.getLogger("backend")
    backend_logger.handlers.clear()
    backend_logger.addHandler(handler)
    backend_logger.setLevel(level)
    backend_logger.propagate = False
