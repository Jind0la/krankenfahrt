"""Configuration — loaded from environment variables with sensible defaults."""

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class Config:
    # Telegram Bot Tokens
    PATIENT_BOT_TOKEN: str = field(default_factory=lambda: os.environ["PATIENT_BOT_TOKEN"])
    DRIVER_BOT_TOKEN: str = field(default_factory=lambda: os.environ["DRIVER_BOT_TOKEN"])
    CHEF_BOT_TOKEN: str = field(default_factory=lambda: os.environ["CHEF_BOT_TOKEN"])

    # Database
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", f"sqlite://{PROJECT_ROOT}/data/krankenfahrt.db"
        )
    )

    # LLM (DeepSeek)
    DEEPSEEK_API_KEY: str = field(default_factory=lambda: os.environ["DEEPSEEK_API_KEY"])
    DEEPSEEK_BASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )
    )

    # Voice (Whisper)
    WHISPER_MODEL: str = field(
        default_factory=lambda: os.environ.get("WHISPER_MODEL", "small")
    )
    WHISPER_DEVICE: str = field(
        default_factory=lambda: os.environ.get("WHISPER_DEVICE", "cpu")
    )
    WHISPER_CACHE_DIR: str = field(
        default_factory=lambda: os.environ.get(
            "WHISPER_CACHE_DIR", "/data/models/whisper"
        )
    )

    # Geo / Routing
    USE_OSRM: bool = field(default_factory=lambda: os.environ.get("USE_OSRM", "0") == "1")
    OSRM_BASE_URL: str = field(
        default_factory=lambda: os.environ.get("OSRM_BASE_URL", "http://localhost:5000")
    )

    # Dispatch Engine
    DISPATCH_MODE: str = field(
        default_factory=lambda: os.environ.get("DISPATCH_MODE", "greedy")
    )  # "greedy" | "ortools"

    # Business
    COMPANY_NAME: str = field(
        default_factory=lambda: os.environ.get("COMPANY_NAME", "Krankenfahrt")
    )
    COMPANY_STREET: str = field(
        default_factory=lambda: os.environ.get("COMPANY_STREET", "Musterstraße 1")
    )
    COMPANY_CITY: str = field(
        default_factory=lambda: os.environ.get("COMPANY_CITY", "12345 Musterstadt")
    )
    COMPANY_PHONE: str = field(
        default_factory=lambda: os.environ.get("COMPANY_PHONE", "+49 123 456789")
    )
    COMPANY_EMAIL: str = field(
        default_factory=lambda: os.environ.get("COMPANY_EMAIL", "info@krankenfahrt.de")
    )
    COMPANY_TAX_ID: str = field(
        default_factory=lambda: os.environ.get("COMPANY_TAX_ID", "DE123456789")
    )
    COMPANY_IK_NUMMER: str = field(
        default_factory=lambda: os.environ.get("COMPANY_IK_NUMMER", "123456789")
    )
    COMPANY_BANK_NAME: str = field(
        default_factory=lambda: os.environ.get("COMPANY_BANK_NAME", "Musterbank")
    )
    COMPANY_IBAN: str = field(
        default_factory=lambda: os.environ.get("COMPANY_IBAN", "DE12 3456 7890 1234 5678 90")
    )
    COMPANY_BIC: str = field(
        default_factory=lambda: os.environ.get("COMPANY_BIC", "MUSTERDEFXXX")
    )

    # Authorization
    ADMIN_TELEGRAM_IDS: list[int] = field(
        default_factory=lambda: [
            int(x.strip())
            for x in os.environ.get("ADMIN_TELEGRAM_IDS", "").split(",")
            if x.strip()
        ]
    )

    # Logging
    LOG_LEVEL: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    # Health check server
    HEALTH_HOST: str = field(
        default_factory=lambda: os.environ.get("HEALTH_HOST", "0.0.0.0")
    )
    HEALTH_PORT: int = field(
        default_factory=lambda: int(os.environ.get("HEALTH_PORT", "8080"))
    )

    # Prometheus metrics server
    METRICS_PORT: int = field(
        default_factory=lambda: int(os.environ.get("METRICS_PORT", "9090"))
    )


config = Config()
