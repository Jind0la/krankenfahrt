"""Verify structlog JSON output — run with: python tests/verify_structlog.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ["LOG_LEVEL"] = "INFO"
os.environ["LOG_FORMAT"] = "json"

from krankenfahrt.logging_setup import setup_logging  # noqa: E402
import structlog  # noqa: E402

setup_logging()
logger = structlog.get_logger("test.verification")

logger.info("application started", service="krankenfahrt")
logger.warning("config value missing", key="SOME_KEY")
logger.error("something went wrong", error_code=42)

try:
    raise ValueError("test exception")
except ValueError:
    logger.exception("caught exception during init")
