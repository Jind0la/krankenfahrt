"""
Structured logging configuration using structlog.

Configures JSON output for log aggregation with standard fields:
timestamp, level, logger (module), event (message), and optional
exception info. Log level is driven by the LOG_LEVEL environment
variable (default: INFO).

Usage (once, at application startup):
    from krankenfahrt.logging_setup import setup_logging
    setup_logging()

After setup, modules use:
    import structlog
    logger = structlog.get_logger()
    logger.info("something happened", extra_field="value")
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    """
    Configure structlog for JSON-structured output.

    Environment variables:
        LOG_LEVEL  — Python log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                     Defaults to INFO.
        LOG_FORMAT — "json" (default) or "console" for human-readable development output.
    """
    log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_format: str = os.environ.get("LOG_FORMAT", "json").lower()

    # --- Shared processors applied to every log entry -----------------------
    shared_processors: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # --- Renderer: JSON for prod, console for dev --------------------------
    if log_format == "console":
        structlog.configure(
            processors=shared_processors
            + [structlog.dev.ConsoleRenderer()],
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=shared_processors
            + [structlog.processors.JSONRenderer()],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    # --- Ensure the stdlib root logger is at the correct level --------------
    # structlog's LoggerFactory creates stdlib loggers under the hood, so we
    # must configure the root handler to actually emit messages.
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any pre-existing handlers so basicConfig calls elsewhere
    # don't produce duplicate or conflicting output.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # Use a ProcessorFormatter so that structlog-processed entries are
    # rendered through the JSONRenderer, while "foreign" log entries
    # (from third-party libraries that use plain logging) get the same
    # structured treatment via foreign_pre_chain.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # --- Silence noisy third-party loggers ----------------------------------
    _NOISY_LOGGERS: tuple[str, ...] = (
        "apscheduler",
        "asyncio",
        "faster_whisper",
        "httpcore",
        "httpx",
        "telegram",
        "telegram.ext",
        "tortoise",
        "urllib3",
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
