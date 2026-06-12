"""LLM fallback chain — try primary provider, fall back to secondary on failure.

Configurable via environment:
  LLM_PRIMARY     — 'openai' or 'deepseek' (default: deepseek)
  LLM_FALLBACK    — provider name for fallback, or '' for none
  LLM_TIMEOUT     — total deadline across all attempts (default: 30.0s)
  LLM_MAX_RETRIES — retries per provider before switching (default: 2)

Usage:
    from krankenfahrt.resilience import call_with_fallback
    result = await call_with_fallback(messages, model="deepseek-chat")
"""

import asyncio
import contextlib
import time

import httpx
import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)

# ── Provider registry ───────────────────────────────────────────────────────

_PROVIDER_CONFIG = {
    "openai": {
        "api_key_attr": "OPENAI_API_KEY",
        "base_url_attr": "OPENAI_BASE_URL",
        "default_model": "gpt-4o",
    },
    "deepseek": {
        "api_key_attr": "DEEPSEEK_API_KEY",
        "base_url_attr": "DEEPSEEK_BASE_URL",
        "default_model": "deepseek-chat",
    },
}

# HTTP statuses that trigger fallback (server errors + rate-limit + timeouts)
_FALLBACK_STATUSES = {429, 500, 502, 503, 504}

# Network errors that trigger fallback
_FALLBACK_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
    httpx.NetworkError,
)


def _get_provider_config(provider: str) -> dict:
    """Resolve provider configuration from environment/Config."""
    if provider not in _PROVIDER_CONFIG:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. Known: {list(_PROVIDER_CONFIG)}"
        )
    cfg = _PROVIDER_CONFIG[provider]
    api_key = getattr(config, cfg["api_key_attr"], None)
    base_url = getattr(config, cfg["base_url_attr"], None)
    if not api_key:
        raise ValueError(
            f"API key not configured for provider '{provider}' "
            f"(set {cfg['api_key_attr']} or ${cfg['api_key_attr'].upper()})"
        )
    return {
        "api_key": api_key,
        "base_url": base_url,
        "default_model": cfg["default_model"],
    }


# ── Core fallback logic ───────────────────────────────────────────────────


async def call_with_fallback(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 300,
    primary_provider: str | None = None,
    fallback_provider: str | None = None,
    total_timeout: float | None = None,
    max_retries: int | None = None,
    rate_limiter=None,  # optional TokenBucket
) -> dict:
    """Call LLM with automatic provider fallback.

    Parameters
    ----------
    messages : list[dict]
        Chat messages in OpenAI format.
    model : str or None
        Model name.  Provider defaults are used when None.
    temperature : float
        Sampling temperature.
    max_tokens : int
        Maximum completion tokens.
    primary_provider : str or None
        Override config.LLM_PRIMARY.
    fallback_provider : str or None
        Override config.LLM_FALLBACK.
    total_timeout : float or None
        Override config.LLM_TIMEOUT.
    max_retries : int or None
        Override config.LLM_MAX_RETRIES.
    rate_limiter : TokenBucket or None
        Optional rate limiter (acquired before each API call).

    Returns
    -------
    dict
        The parsed JSON response body from the successful provider call.

    Raises
    ------
    RuntimeError
        If all providers are exhausted without success.
    """
    primary = primary_provider or config.LLM_PRIMARY
    fallback = fallback_provider or config.LLM_FALLBACK
    timeout = total_timeout or config.LLM_TIMEOUT
    retries = max_retries if max_retries is not None else config.LLM_MAX_RETRIES

    # Build provider chain
    providers = [primary]
    if fallback and fallback != primary:
        providers.append(fallback)

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    total_attempts = 0

    for provider in providers:
        provider_cfg = _get_provider_config(provider)
        active_model = model or provider_cfg["default_model"]

        for attempt in range(retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    "llm_total_timeout_exceeded",
                    deadline=timeout,
                    providers_tried=providers[: providers.index(provider)],
                    total_attempts=total_attempts,
                )
                raise TimeoutError(
                    f"LLM total timeout ({timeout}s) exceeded after "
                    f"{total_attempts} attempts across {providers[:providers.index(provider)]}"
                )

            total_attempts += 1

            # Rate-limit gate
            if rate_limiter is not None:
                acquired = await rate_limiter.acquire()
                if not acquired:
                    logger.warning(
                        "llm_rate_limit_deferred",
                        provider=provider,
                        attempt=attempt + 1,
                    )

            try:
                result = await _call_provider(
                    provider_cfg,
                    active_model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=min(remaining, 15.0),
                )

                # Log if we used a fallback provider
                if provider != primary:
                    logger.info(
                        "llm_fallback_used",
                        fallback_provider=provider,
                        attempt=attempt + 1,
                        total_attempts=total_attempts,
                    )
                elif attempt > 0:
                    logger.info(
                        "llm_retry_succeeded",
                        provider=provider,
                        attempt=attempt + 1,
                        total_attempts=total_attempts,
                    )

                return result

            except _FALLBACK_EXCEPTIONS as exc:
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    provider=provider,
                    model=active_model,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                    remaining_s=round(remaining, 1),
                )
                if attempt < retries:
                    backoff = min(2**attempt, 8.0)
                    logger.debug(
                        "llm_retry_backoff",
                        provider=provider,
                        delay_s=backoff,
                    )
                    await asyncio.sleep(backoff)
                # If retries exhausted for this provider, loop moves to fallback

            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                logger.warning(
                    "llm_http_error",
                    provider=provider,
                    model=active_model,
                    attempt=attempt + 1,
                    status_code=status,
                    response_body=exc.response.text[:300],
                    remaining_s=round(remaining, 1),
                )
                if status in _FALLBACK_STATUSES:
                    # Retriable — backoff and try again (or fall through to fallback)
                    if attempt < retries:
                        backoff = min(2**attempt, 8.0)
                        # If 429 with Retry-After header, honor it
                        retry_after = exc.response.headers.get("Retry-After")
                        if retry_after is not None:
                            with contextlib.suppress(ValueError):
                                backoff = float(retry_after)
                        logger.debug(
                            "llm_retry_backoff",
                            provider=provider,
                            delay_s=backoff,
                            retry_after_header=retry_after,
                        )
                        await asyncio.sleep(backoff)
                else:
                    # Non-retriable (4xx except 429) — don't retry, move to fallback
                    logger.error(
                        "llm_non_retriable_error",
                        provider=provider,
                        status_code=status,
                    )
                    break  # break inner retry loop, move to next provider

            except Exception as exc:
                last_error = exc
                logger.error(
                    "llm_unexpected_error",
                    provider=provider,
                    model=active_model,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
                # Unexpected errors — don't retry, move to fallback
                break

    # All providers exhausted
    raise RuntimeError(
        f"All LLM providers exhausted after {total_attempts} attempts. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    ) from last_error


async def _call_provider(
    provider_cfg: dict,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> dict:
    """Execute a single provider call and return parsed JSON body."""
    url = f"{provider_cfg['base_url']}/chat/completions"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {provider_cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
