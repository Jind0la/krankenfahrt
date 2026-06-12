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

    # --- Choose renderer based on LOG_FORMAT -------------------------------
    renderer = structlog.dev.ConsoleRenderer() if log_format == "console" else structlog.processors.JSONRenderer()

    # --- Configure structlog (same factory for both paths) -------------------
    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- Set up the stdlib root handler -------------------------------------
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # --- Silence noisy third-party loggers ----------------------------------
    _NOISY_LOGGERS: tuple[str, ...] = (  # noqa: N806
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
