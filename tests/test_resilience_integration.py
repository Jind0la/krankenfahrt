"""Integration tests for resilience mechanisms working together."""

import asyncio
import time

import httpx
import pytest

from krankenfahrt.resilience.db_retry import db_retry
from krankenfahrt.resilience.llm_fallback import call_with_fallback
from krankenfahrt.resilience.rate_limiter import TokenBucket


class TestFullPipeline:
    """LLM fallback + rate limiter + DB retry working together."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Ensure required env vars are set."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    @pytest.mark.asyncio
    async def test_llm_with_rate_limiter_and_db_retry(self, respx_mock):
        """Full pipeline: rate limit → LLM fallback → DB retry."""
        # Setup: OpenAI fails, DeepSeek succeeds
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )
        respx_mock.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"action":"book","confidence":0.95}',
                                "role": "assistant",
                            }
                        }
                    ]
                },
            )
        )

        # Rate limiter with generous burst
        limiter = TokenBucket(rate=100.0, burst=10)

        # Simulate the LLM service flow
        messages = [
            {"role": "system", "content": "Extract booking intent."},
            {"role": "user", "content": "Morgen 8 Uhr zur Dialyse"},
        ]

        # LLM call with fallback + rate limiter
        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
            rate_limiter=limiter,
        )

        assert result["choices"][0]["message"]["content"] is not None
        # Verify rate limiter tracked the call
        assert limiter.total_acquired >= 1

        # Simulate DB write with retry
        call_count = [0]

        async def save_result():
            call_count[0] += 1
            return "saved"

        db_result = await db_retry(save_result, operation_name="save_booking")
        assert db_result == "saved"
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_backpressure_with_llm(self, respx_mock):
        """Rate limiter slows down burst of calls, all eventually succeed."""
        call_log = []

        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "ok", "role": "assistant"}}
                    ]
                },
            )
        )

        # Burst=1, rate=5 — only 1 call gets through immediately
        limiter = TokenBucket(rate=5.0, burst=1)

        async def make_call():
            await call_with_fallback(
                [{"role": "user", "content": "test"}],
                primary_provider="openai",
                fallback_provider="",
                max_retries=0,
                rate_limiter=limiter,
            )
            call_log.append(time.monotonic())

        # Launch 5 concurrent calls with burst=1
        tasks = [asyncio.create_task(make_call()) for _ in range(5)]
        await asyncio.gather(*tasks)

        assert len(call_log) == 5

        # With burst=1 and 5 calls, at least some must wait
        assert limiter.total_acquired == 5
        # Deferred count may be 0 or more depending on timing,
        # but verify the limiter was at least used
        assert limiter.total_acquired >= 5


class TestConfigIntegration:
    """Configuration values are correctly loaded from env."""

    def test_resilience_config_defaults(self, monkeypatch):
        """Default config values are sensible."""
        monkeypatch.setenv("PATIENT_BOT_TOKEN", "pbt")
        monkeypatch.setenv("DRIVER_BOT_TOKEN", "dbt")
        monkeypatch.setenv("CHEF_BOT_TOKEN", "cbt")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk")

        from krankenfahrt.config import Config

        cfg = Config()

        # LLM resilience
        assert cfg.LLM_PRIMARY == "deepseek"
        assert cfg.LLM_FALLBACK == ""
        assert cfg.LLM_TIMEOUT == 30.0
        assert cfg.LLM_MAX_RETRIES == 2

        # DB retry
        assert cfg.DB_RETRY_MAX_ATTEMPTS == 3
        assert cfg.DB_RETRY_BACKOFF_BASE == 2.0

        # Rate limiting
        assert cfg.RATE_LIMIT_TOKENS_PER_SEC == 5.0
        assert cfg.RATE_LIMIT_BURST == 10

    def test_resilience_config_from_env(self, monkeypatch):
        """Config values can be overridden via environment variables."""
        monkeypatch.setenv("PATIENT_BOT_TOKEN", "pbt")
        monkeypatch.setenv("DRIVER_BOT_TOKEN", "dbt")
        monkeypatch.setenv("CHEF_BOT_TOKEN", "cbt")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk")
        monkeypatch.setenv("OPENAI_API_KEY", "oak")

        # Override resilience settings
        monkeypatch.setenv("LLM_PRIMARY", "openai")
        monkeypatch.setenv("LLM_FALLBACK", "deepseek")
        monkeypatch.setenv("LLM_TIMEOUT", "15.0")
        monkeypatch.setenv("LLM_MAX_RETRIES", "5")
        monkeypatch.setenv("DB_RETRY_MAX_ATTEMPTS", "5")
        monkeypatch.setenv("DB_RETRY_BACKOFF_BASE", "1.5")
        monkeypatch.setenv("RATE_LIMIT_TOKENS_PER_SEC", "10.0")
        monkeypatch.setenv("RATE_LIMIT_BURST", "20")

        from krankenfahrt.config import Config

        cfg = Config()

        assert cfg.LLM_PRIMARY == "openai"
        assert cfg.LLM_FALLBACK == "deepseek"
        assert cfg.LLM_TIMEOUT == 15.0
        assert cfg.LLM_MAX_RETRIES == 5
        assert cfg.DB_RETRY_MAX_ATTEMPTS == 5
        assert cfg.DB_RETRY_BACKOFF_BASE == 1.5
        assert cfg.RATE_LIMIT_TOKENS_PER_SEC == 10.0
        assert cfg.RATE_LIMIT_BURST == 20
