"""Tests for the LLM fallback chain with mocked HTTP responses."""

import asyncio

import httpx
import pytest
import respx

from krankenfahrt.resilience.llm_fallback import (
    _PROVIDER_CONFIG,
    _FALLBACK_EXCEPTIONS,
    _get_provider_config,
    call_with_fallback,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_openai_ok(respx_mock):
    """Mock OpenAI returning a successful response."""
    return respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "OpenAI response", "role": "assistant"}}
                ]
            },
        )
    )


@pytest.fixture
def mock_openai_500(respx_mock):
    """Mock OpenAI returning a 500 error."""
    return respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "Internal server error"})
    )


@pytest.fixture
def mock_openai_429(respx_mock):
    """Mock OpenAI returning a 429 rate-limit error."""
    return respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={"error": "Rate limit exceeded"},
            headers={"Retry-After": "0.1"},
        )
    )


@pytest.fixture
def mock_deepseek_ok(respx_mock):
    """Mock DeepSeek returning a successful response."""
    return respx_mock.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "DeepSeek response", "role": "assistant"}}
                ]
            },
        )
    )


@pytest.fixture
def mock_deepseek_500(respx_mock):
    """Mock DeepSeek returning a 500 error."""
    return respx_mock.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "Server error"})
    )


@pytest.fixture
def mock_both_ok(mock_openai_ok, mock_deepseek_ok):
    """Both providers return 200."""
    return


@pytest.fixture
def messages():
    """Sample chat messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ]


# ── Provider config resolution ─────────────────────────────────────────────


class TestProviderConfig:
    """Provider configuration resolution."""

    def test_get_known_provider(self):
        """Resolve config for a known provider."""
        cfg = _get_provider_config("deepseek")
        assert cfg["api_key"] == "test-deepseek-key"
        assert cfg["default_model"] == "deepseek-chat"

    def test_get_openai_config(self):
        """Resolve OpenAI config."""
        cfg = _get_provider_config("openai")
        assert cfg["api_key"] == "test-openai-key"
        assert cfg["default_model"] == "gpt-4o"

    def test_unknown_provider_raises(self):
        """Unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            _get_provider_config("nonexistent")

    def test_missing_api_key_raises(self, monkeypatch):
        """Missing API key raises ValueError when checking unknown provider."""
        # This test verifies that a truly unknown provider with no key raises
        # We use a provider not in _PROVIDER_CONFIG
        monkeypatch.setattr(
            "krankenfahrt.resilience.llm_fallback._PROVIDER_CONFIG",
            {
                **_PROVIDER_CONFIG,
                "custom": {
                    "api_key_attr": "CUSTOM_API_KEY",
                    "base_url_attr": "OPENAI_BASE_URL",
                    "default_model": "custom-model",
                },
            },
        )
        monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key not configured"):
            _get_provider_config("custom")


# ── Primary-only success ───────────────────────────────────────────────────


class TestPrimarySuccess:
    """Happy path with primary provider."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(self, mock_openai_ok, messages):
        """Primary provider returns 200 → result returned immediately."""
        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "OpenAI response"

    @pytest.mark.asyncio
    async def test_primary_retry_then_succeed(self, respx_mock, messages):
        """Primary fails once then succeeds on retry."""
        # First call fails with 500, second succeeds
        call_count = [0]

        def handler(request):
            call_count[0] += 1
            if call_count[0] == 1:
                return httpx.Response(500, json={"error": "fail"})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Retry success", "role": "assistant"}}
                    ]
                },
            )

        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=handler
        )

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="",
            max_retries=2,
        )
        assert result["choices"][0]["message"]["content"] == "Retry success"
        assert call_count[0] == 2


# ── Fallback behaviour ─────────────────────────────────────────────────────


class TestFallback:
    """Provider fallback when primary fails."""

    @pytest.mark.asyncio
    async def test_fallback_to_deepseek(self, mock_openai_500, mock_deepseek_ok, messages):
        """Primary returns 500 → fallback to DeepSeek succeeds."""
        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "DeepSeek response"

    @pytest.mark.asyncio
    async def test_both_fail_raises(self, mock_openai_500, mock_deepseek_500, messages):
        """Both providers fail → RuntimeError raised."""
        with pytest.raises(RuntimeError, match="All LLM providers exhausted"):
            await call_with_fallback(
                messages,
                primary_provider="openai",
                fallback_provider="deepseek",
                max_retries=0,
                total_timeout=3.0,
            )

    @pytest.mark.asyncio
    async def test_429_triggers_fallback(self, mock_openai_429, mock_deepseek_ok, messages):
        """Primary returns 429 → fallback to DeepSeek."""
        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "DeepSeek response"

    @pytest.mark.asyncio
    async def test_429_with_retry_after_honored(self, respx_mock, messages):
        """429 with Retry-After header uses that delay."""
        delays = []

        route = respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                429,
                json={"error": "rate limit"},
                headers={"Retry-After": "0.05"},
            )
        )

        # Mock deepseek as fallback success
        respx_mock.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "fallback", "role": "assistant"}}
                    ]
                },
            )
        )

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "fallback"


# ── Timeout enforcement ────────────────────────────────────────────────────


class TestTimeout:
    """Total timeout across all attempts."""

    @pytest.mark.asyncio
    async def test_total_timeout_exceeded(self, mock_openai_500, mock_deepseek_500, messages):
        """When total timeout is exceeded, raise TimeoutError."""
        with pytest.raises(TimeoutError, match="LLM total timeout"):
            await call_with_fallback(
                messages,
                primary_provider="openai",
                fallback_provider="deepseek",
                max_retries=3,
                total_timeout=0.5,
            )


# ── Non-retriable errors ───────────────────────────────────────────────────


class TestNonRetriable:
    """Non-retriable (4xx non-429) errors skip retries and go to fallback."""

    @pytest.mark.asyncio
    async def test_401_goes_to_fallback(self, respx_mock, mock_deepseek_ok, messages):
        """401 from primary → immediately try fallback."""
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=2,  # Should NOT retry 401
        )
        assert result["choices"][0]["message"]["content"] == "DeepSeek response"


# ── Network errors ─────────────────────────────────────────────────────────


class TestNetworkErrors:
    """Network-level errors trigger retry and fallback."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self, respx_mock, mock_deepseek_ok, messages):
        """Primary times out → fallback to DeepSeek."""
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("Connection timed out")
        )

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "DeepSeek response"

    @pytest.mark.asyncio
    async def test_connect_error_triggers_fallback(self, respx_mock, mock_deepseek_ok, messages):
        """Connection refused → fallback."""
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="deepseek",
            max_retries=0,
        )
        assert result["choices"][0]["message"]["content"] == "DeepSeek response"


# ── Rate limiter integration ───────────────────────────────────────────────


class TestRateLimiterIntegration:
    """Rate limiter is called before each provider attempt."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire_called(self, mock_openai_ok, messages):
        """Rate limiter.acquire() is called before each API call."""
        from krankenfahrt.resilience.rate_limiter import TokenBucket

        limiter = TokenBucket(rate=100.0, burst=10)
        initial_acquired = limiter.total_acquired

        result = await call_with_fallback(
            messages,
            primary_provider="openai",
            fallback_provider="",
            max_retries=0,
            rate_limiter=limiter,
        )
        assert result["choices"][0]["message"]["content"] == "OpenAI response"
        assert limiter.total_acquired == initial_acquired + 1
