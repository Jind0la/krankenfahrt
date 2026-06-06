"""Tests for the token-bucket rate limiter."""

import asyncio
import time

import pytest

from krankenfahrt.resilience.rate_limiter import TokenBucket, reset_global_limiter


class TestTokenBucketBasic:
    """Core token bucket behaviour."""

    def test_initial_tokens_equal_burst(self):
        """Bucket starts full with burst capacity."""
        bucket = TokenBucket(rate=5.0, burst=10)
        assert bucket.available_tokens == pytest.approx(10.0, abs=0.01)

    def test_negative_rate_raises(self):
        """Negative rate should raise ValueError."""
        with pytest.raises(ValueError, match="rate must be positive"):
            TokenBucket(rate=-1.0, burst=10)

    def test_zero_rate_raises(self):
        """Zero rate should raise ValueError."""
        with pytest.raises(ValueError, match="rate must be positive"):
            TokenBucket(rate=0, burst=10)

    def test_negative_burst_raises(self):
        """Negative burst should raise ValueError."""
        with pytest.raises(ValueError, match="burst must be positive"):
            TokenBucket(rate=5.0, burst=-5)

    def test_zero_burst_raises(self):
        """Zero burst should raise ValueError."""
        with pytest.raises(ValueError, match="burst must be positive"):
            TokenBucket(rate=5.0, burst=0)

    @pytest.mark.asyncio
    async def test_acquire_consumes_token(self):
        """acquire() reduces available tokens by one."""
        bucket = TokenBucket(rate=100.0, burst=10)
        before = bucket.available_tokens
        acquired = await bucket.acquire()
        assert acquired is True
        assert bucket.available_tokens == pytest.approx(before - 1.0, abs=0.05)

    @pytest.mark.asyncio
    async def test_try_acquire_succeeds_when_tokens_available(self):
        """try_acquire returns True when tokens are available."""
        bucket = TokenBucket(rate=100.0, burst=10)
        assert await bucket.try_acquire() is True

    @pytest.mark.asyncio
    async def test_try_acquire_non_blocking(self):
        """try_acquire returns immediately even when no tokens."""
        bucket = TokenBucket(rate=0.001, burst=1)  # Very slow refill
        # Drain the bucket
        await bucket.acquire()
        # Now try_acquire should return False immediately (non-blocking)
        start = time.monotonic()
        result = await bucket.try_acquire()
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 0.1  # Should be nearly instant


class TestTokenBucketRefill:
    """Token refill behaviour."""

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        """Available tokens increase as time passes."""
        bucket = TokenBucket(rate=100.0, burst=10)

        # Drain all tokens
        for _ in range(10):
            await bucket.acquire()

        assert bucket.available_tokens < 0.5

        # Wait for refill
        await asyncio.sleep(0.1)  # Should refill ~10 tokens at rate=100

        assert bucket.available_tokens > 1.0

    @pytest.mark.asyncio
    async def test_tokens_capped_at_burst(self):
        """Available tokens never exceed burst capacity."""
        bucket = TokenBucket(rate=1000.0, burst=5)

        # Wait enough time that would exceed burst if uncapped
        await asyncio.sleep(0.5)

        assert bucket.available_tokens <= 5.0 + 0.01  # float tolerance

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_concurrent(self):
        """Rate limiting works with concurrent acquirers."""
        bucket = TokenBucket(rate=50.0, burst=10)
        results = []

        async def worker():
            acquired = await bucket.acquire(timeout=5.0)
            results.append(acquired)

        # Launch 15 concurrent workers — burst is 10, rate is 50/s
        tasks = [asyncio.create_task(worker()) for _ in range(15)]
        await asyncio.gather(*tasks)

        # All should eventually acquire within timeout since rate is 50/s
        assert all(results), f"{results.count(False)} workers failed to acquire"
        assert bucket.total_deferred > 0  # Some should have been deferred


class TestTokenBucketStats:
    """Statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_track_acquired(self):
        """total_acquired counter increments."""
        bucket = TokenBucket(rate=100.0, burst=10)
        for _ in range(3):
            await bucket.acquire()
        assert bucket.total_acquired == 3

    @pytest.mark.asyncio
    async def test_stats_track_deferred(self):
        """total_deferred counter increments when waiting was required."""
        bucket = TokenBucket(rate=5.0, burst=1)
        await bucket.acquire()  # Drain
        # Next acquire should need to wait
        task = asyncio.create_task(bucket.acquire(timeout=5.0))
        await asyncio.sleep(0.3)  # Let it refill and acquire
        await task
        assert bucket.total_deferred >= 1

    @pytest.mark.asyncio
    async def test_stats_dict(self):
        """stats() returns a dict with expected keys."""
        bucket = TokenBucket(rate=5.0, burst=10, name="test-bucket")
        stats = bucket.stats()
        assert stats["name"] == "test-bucket"
        assert stats["rate"] == 5.0
        assert stats["burst"] == 10
        assert "tokens_available" in stats
        assert "total_acquired" in stats


class TestGlobalLimiter:
    """Global singleton behaviour."""

    def test_get_global_returns_same_instance(self):
        """get_global_limiter returns singleton."""
        from krankenfahrt.resilience.rate_limiter import get_global_limiter

        reset_global_limiter()
        limiter1 = get_global_limiter()
        limiter2 = get_global_limiter()
        assert limiter1 is limiter2

    def test_reset_creates_new_instance(self):
        """reset_global_limiter creates a fresh singleton."""
        from krankenfahrt.resilience.rate_limiter import get_global_limiter

        reset_global_limiter()
        old = get_global_limiter()
        reset_global_limiter()
        new = get_global_limiter()
        assert old is not new
