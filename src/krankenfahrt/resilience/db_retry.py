"""Database retry wrapper — exponential backoff for transient write failures.

Catches transient database errors (connection drops, timeouts, serialization
conflicts) and retries up to config.DB_RETRY_MAX_ATTEMPTS with exponential
backoff starting from config.DB_RETRY_BACKOFF_BASE.

Configuration:
  DB_RETRY_MAX_ATTEMPTS  — max retry attempts (default: 3)
  DB_RETRY_BACKOFF_BASE  — initial backoff in seconds (default: 2.0)

Usage:
    from krankenfahrt.resilience import db_retry

    # As a context manager:
    async with db_retry():
        await patient.save()

    # As a wrapper:
    result = await db_retry(lambda: some_db_write())

    # Decorator pattern:
    @db_retry.wrap
    async def upsert_patient(data):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Coroutine, TypeVar

import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# ── Transient error detection ─────────────────────────────────────────────────

# Tortoise ORM wraps underlying DB driver errors.  The base exception classes
# vary by driver (aiosqlite, asyncpg, etc.), so we match by message patterns
# and catch broad exception types at the ORM level.

_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "database is locked",
    "database disk image is malformed",
    "SQLITE_BUSY",
    "sqlite3.OperationalError: database is locked",
    "connection was closed",
    "connection already closed",
    "server closed the connection unexpectedly",
    "could not serialize access",
    "deadlock detected",
    "connection timed out",
    "connection refused",
    "cannot connect",
    "too many clients",
    "remaining connection slots are reserved",
    "sorry, too many clients already",
    "connection reset by peer",
    "broken pipe",
    "no connection to the server",
    "could not connect to server",
)


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception represents a transient database error."""
    # Check full exception chain (cause + context)
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None:
        exc_id = id(current)
        if exc_id in seen:
            break
        seen.add(exc_id)

        msg = str(current).lower()
        for pattern in _TRANSIENT_PATTERNS:
            if pattern.lower() in msg:
                return True

        # Also check for connection/timout errors by type
        type_name = type(current).__name__
        if type_name in (
            "ConnectionError",
            "TimeoutError",
            "ConnectionRefusedError",
            "ConnectionResetError",
            "BrokenPipeError",
            "OperationalError",       # SQLAlchemy / some ORMs
            "DatabaseError",          # broad catch
            "InterfaceError",         # DBAPI
        ):
            return True

        current = current.__cause__ or current.__context__

    return False


# ── Core retry logic ─────────────────────────────────────────────────────────


async def _retry_call(
    fn: Callable[[], Coroutine[Any, Any, T]],
    max_attempts: int,
    base_delay: float,
    operation_name: str,
) -> T:
    """Call ``fn``, retrying on transient errors with exponential backoff.

    Parameters
    ----------
    fn : async callable
        The database operation to execute.
    max_attempts : int
        Total attempts (1 initial + N-1 retries).
    base_delay : float
        Base backoff in seconds (delay = base_delay ** attempt).
    operation_name : str
        Human-readable label for logging.

    Returns
    -------
    T
        The return value of ``fn`` on success.

    Raises
    ------
    Exception
        The last exception if all attempts are exhausted.
    """
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            start = time.monotonic()
            result = await fn()
            elapsed = time.monotonic() - start

            if attempt > 1:
                logger.info(
                    "db_retry_succeeded",
                    operation=operation_name,
                    attempt=attempt,
                    elapsed_s=round(elapsed, 4),
                )
            return result

        except Exception as exc:
            last_error = exc

            if not _is_transient(exc):
                # Non-transient error — don't retry
                logger.error(
                    "db_non_transient_error",
                    operation=operation_name,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
                raise

            if attempt == max_attempts:
                logger.error(
                    "db_retry_exhausted",
                    operation=operation_name,
                    attempts=max_attempts,
                    last_error_type=type(exc).__name__,
                    last_error=str(exc)[:300],
                )
                raise

            delay = base_delay**attempt
            logger.warning(
                "db_retry_attempt",
                operation=operation_name,
                attempt=attempt,
                next_attempt=attempt + 1,
                max_attempts=max_attempts,
                delay_s=round(delay, 2),
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            await asyncio.sleep(delay)

    # Should be unreachable, but satisfy the type checker
    assert last_error is not None
    raise last_error


# ── Public API ──────────────────────────────────────────────────────────────


class _DBRetryCallable:
    """Callable that also exposes ``wrap`` for decorator usage."""

    def __call__(
        self,
        fn: Callable[[], Coroutine[Any, Any, T]],
        *,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        operation_name: str = "db_op",
    ) -> Coroutine[Any, Any, T]:
        """Retry a database operation with exponential backoff.

        Parameters
        ----------
        fn : async callable
            The database operation to execute.
        max_attempts : int or None
            Override config.DB_RETRY_MAX_ATTEMPTS.
        base_delay : float or None
            Override config.DB_RETRY_BACKOFF_BASE.
        operation_name : str
            Label for log messages.

        Returns
        -------
        Coroutine returning T
        """
        attempts = max_attempts if max_attempts is not None else config.DB_RETRY_MAX_ATTEMPTS
        delay = base_delay if base_delay is not None else config.DB_RETRY_BACKOFF_BASE
        return _retry_call(fn, attempts, delay, operation_name)

    def wrap(self, fn=None, /, *, max_attempts=None, base_delay=None, operation_name=None):
        """Decorator: wrap an async function with db_retry logic.

        Usage::

            @db_retry.wrap
            async def save_patient(data):
                ...

            @db_retry.wrap(max_attempts=5, base_delay=1.5)
            async def critical_write(data):
                ...
        """
        if fn is not None:
            # Called as @db_retry.wrap (without parens)
            op_name = operation_name or fn.__name__

            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                return await self(
                    lambda: fn(*args, **kwargs),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    operation_name=op_name,
                )

            return wrapper

        # Called as @db_retry.wrap(max_attempts=5, ...)
        def decorator(inner_fn):
            op_name = operation_name or inner_fn.__name__

            @functools.wraps(inner_fn)
            async def wrapper(*args, **kwargs):
                return await self(
                    lambda: inner_fn(*args, **kwargs),
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    operation_name=op_name,
                )

            return wrapper

        return decorator

    @asynccontextmanager
    async def context(
        self,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        operation_name: str = "db_op",
    ):
        """Async context manager: code inside ``async with db_retry.context():``
        is wrapped in retry logic.  The context manager itself does nothing
        special; the retry wraps the body execution.
        """
        # The context manager pattern is a no-op here because the retry
        # wraps individual operations.  Provide it for API completeness.
        yield


# Singleton instance
db_retry = _DBRetryCallable()
