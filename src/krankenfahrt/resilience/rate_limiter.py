"""Token-bucket rate limiter for outbound API calls.

Prevents exceeding configured rate limits (e.g. LLM provider quotas) by
queuing requests when tokens are exhausted.  Uses the token-bucket
algorithm with configurable fill rate and burst size.

Configuration:
  RATE_LIMIT_TOKENS_PER_SEC  — tokens added per second (default: 5.0)
  RATE_LIMIT_BURST           — maximum token capacity (default: 10)

Usage:
    from krankenfahrt.resilience import get_global_limiter

    limiter = get_global_limiter()
    acquired = await limiter.acquire()
    if not acquired:
        # Handle rate-limit deferred (e.g. return 429 + Retry-After)
        ...
"""

from __future__ import annotations

import asyncio
import time

import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)

# ── Token bucket ────────────────────────────────────────────────────────────


class TokenBucket:
    """Thread-safe async token-bucket rate limiter.

    Tokens are added at a fixed rate up to a maximum burst capacity.
    When tokens are exhausted, ``acquire()`` blocks until a token
    becomes available or the optional timeout expires.

    Parameters
    ----------
    rate : float
        Tokens added per second.
    burst : int
        Maximum token capacity (bucket size).
    name : str
        Label for log messages.

    Example
    -------
    >>> bucket = TokenBucket(rate=5.0, burst=10)
    >>> acquired = await bucket.acquire()
    >>> if acquired:
    ...     await make_api_call()
    """

    def __init__(self, rate: float, burst: int, name: str = "default") -> None:
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        if burst <= 0:
            raise ValueError(f"burst must be positive, got {burst}")

        self.rate = float(rate)
        self.burst = burst
        self.name = name

        self._tokens: float = float(burst)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

        # Statistics
        self.total_acquired: int = 0
        self.total_deferred: int = 0
        self.total_wait_s: float = 0.0

    # ── public API ──────────────────────────────────────────────────────

    async def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire one token, blocking until available or timeout.

        Parameters
        ----------
        timeout : float
            Maximum seconds to wait for a token.

        Returns
        -------
        bool
            True if a token was acquired, False on timeout.
        """
        deadline = time.monotonic() + timeout

        # Quick path: try to acquire without waiting
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self.total_acquired += 1
                return True

        # Slow path: loop with timed waits
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self.total_acquired += 1
                    return True

                # Calculate how long until a token is available
                needed = 1.0 - self._tokens
                wait_s = needed / self.rate

            # Check if we'd exceed the total timeout
            now = time.monotonic()
            remaining = deadline - now
            if wait_s >= remaining:
                logger.warning(
                    "rate_limiter_timeout",
                    name=self.name,
                    timeout_s=timeout,
                    tokens_available=round(self._tokens, 3),
                )
                return False

            # Wait outside the lock so other waiters can process
            self.total_deferred += 1
            await asyncio.sleep(wait_s)

    async def try_acquire(self) -> bool:
        """Acquire a token if one is immediately available (non-blocking).

        Returns
        -------
        bool
            True if acquired, False if no tokens available.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self.total_acquired += 1
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (best-effort, not locked)."""
        elapsed = time.monotonic() - self._last_refill
        return min(float(self.burst), self._tokens + elapsed * self.rate)

    def stats(self) -> dict:
        """Return current statistics."""
        return {
            "name": self.name,
            "rate": self.rate,
            "burst": self.burst,
            "tokens_available": round(self.available_tokens, 3),
            "total_acquired": self.total_acquired,
            "total_deferred": self.total_deferred,
            "total_wait_s": round(self.total_wait_s, 3),
        }

    # ── internals ───────────────────────────────────────────────────────

    def _refill(self) -> None:
        """Refill tokens based on elapsed time.  Must be called inside lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate)
        self._last_refill = now


# ── Global singleton ────────────────────────────────────────────────────────

_global_limiter: TokenBucket | None = None


def get_global_limiter() -> TokenBucket:
    """Return the global token-bucket instance, creating it on first call."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = TokenBucket(
            rate=config.RATE_LIMIT_TOKENS_PER_SEC,
            burst=config.RATE_LIMIT_BURST,
            name="llm-outbound",
        )
        logger.info(
            "rate_limiter_initialized",
            rate=config.RATE_LIMIT_TOKENS_PER_SEC,
            burst=config.RATE_LIMIT_BURST,
        )
    return _global_limiter


def reset_global_limiter() -> None:
    """Reset the global limiter (useful for testing)."""
    global _global_limiter
    _global_limiter = None
