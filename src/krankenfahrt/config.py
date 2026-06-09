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

    # LLM (Primary + Fallback)
    LLM_PRIMARY: str = field(
        default_factory=lambda: os.environ.get("LLM_PRIMARY", "deepseek")
    )  # "openai" | "deepseek"
    LLM_FALLBACK: str = field(
        default_factory=lambda: os.environ.get("LLM_FALLBACK", "")
    )  # e.g. "deepseek" when primary is "openai", or "" for no fallback
    LLM_TIMEOUT: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TIMEOUT", "30.0"))
    )  # Total timeout across all fallback attempts (seconds)
    LLM_MAX_RETRIES: int = field(
        default_factory=lambda: int(os.environ.get("LLM_MAX_RETRIES", "2"))
    )  # Retries per provider before falling back

    # OpenAI (primary)
    OPENAI_API_KEY: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    OPENAI_BASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
    )

    # DeepSeek (default primary / fallback)
    DEEPSEEK_API_KEY: str = field(default_factory=lambda: os.environ["DEEPSEEK_API_KEY"])
    DEEPSEEK_BASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )
    )

    # Database retry
    DB_RETRY_MAX_ATTEMPTS: int = field(
        default_factory=lambda: int(os.environ.get("DB_RETRY_MAX_ATTEMPTS", "3"))
    )
    DB_RETRY_BACKOFF_BASE: float = field(
        default_factory=lambda: float(os.environ.get("DB_RETRY_BACKOFF_BASE", "2.0"))
    )

    # Rate limiting (token bucket for outbound LLM calls)
    RATE_LIMIT_TOKENS_PER_SEC: float = field(
        default_factory=lambda: float(os.environ.get("RATE_LIMIT_TOKENS_PER_SEC", "5.0"))
    )
    RATE_LIMIT_BURST: int = field(
        default_factory=lambda: int(os.environ.get("RATE_LIMIT_BURST", "10"))
    )

    # Voice (Whisper)
    WHISPER_MODEL: str = field(
        default_factory=lambda: os.environ.get("WHISPER_MODEL", "tiny")
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

    # Escalation Management
    ESCALATION_TIMEOUT_MINUTES: int = field(
        default_factory=lambda: int(os.environ.get("ESCALATION_TIMEOUT_MINUTES", "30"))
    )  # Auto-escalate if no status update in this many minutes
    ESCALATION_ENABLED: bool = field(
        default_factory=lambda: os.environ.get("ESCALATION_ENABLED", "1") == "1"
    )

    # Prometheus metrics server
    METRICS_PORT: int = field(
        default_factory=lambda: int(os.environ.get("METRICS_PORT", "9090"))
    )

    # ── Alerting ─────────────────────────────────────────────────
    ALERTING_ENABLED: bool = field(
        default_factory=lambda: os.environ.get("ALERTING_ENABLED", "0") == "1"
    )
    ALERTING_EVAL_INTERVAL: float = field(
        default_factory=lambda: float(os.environ.get("ALERTING_EVAL_INTERVAL", "30.0"))
    )
    ALERTING_CHEF_CHAT_ID: int = field(
        default_factory=lambda: int(os.environ.get("ALERTING_CHEF_CHAT_ID", "0"))
    )
    ALERTING_ERROR_RATE_THRESHOLD: float = field(
        default_factory=lambda: float(os.environ.get("ALERTING_ERROR_RATE_THRESHOLD", "0.1"))
    )
    ALERTING_ERROR_RATE_DURATION: float = field(
        default_factory=lambda: float(os.environ.get("ALERTING_ERROR_RATE_DURATION", "60.0"))
    )
    ALERTING_COOLDOWN: float = field(
        default_factory=lambda: float(os.environ.get("ALERTING_COOLDOWN", "300.0"))
    )
    ALERTING_DEADMAN_MAX_AGE: float = field(
        default_factory=lambda: float(os.environ.get("ALERTING_DEADMAN_MAX_AGE", "60.0"))
    )


config = Config()
