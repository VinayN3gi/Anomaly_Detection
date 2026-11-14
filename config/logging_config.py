"""Structured logging configuration for AIOps Website Monitoring Platform.

Provides JSON-formatted logging for containerized and production environments,
and human-readable colored or formatted output for local development.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        # Include exception trace if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if provided
        extra_keys = set(record.__dict__.keys()) - {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
        }
        for key in extra_keys:
            log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


def setup_logging(
    default_level: str = "INFO",
    log_format: str | None = None,
) -> None:
    """Initialize structured logging across the application.

    Args:
        default_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: 'json' for production/docker, 'console' for local development.
    """
    level_name = os.getenv("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt_type = (log_format or os.getenv("LOG_FORMAT", "console")).lower()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)

    if fmt_type == "json":
        stream_handler.setFormatter(JSONFormatter())
    else:
        console_fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        stream_handler.setFormatter(console_fmt)

    root_logger.addHandler(stream_handler)

    # Silence overly verbose external loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger instance with the given module name."""
    return logging.getLogger(name)

