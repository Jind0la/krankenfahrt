"""Error handling & resilience package.

Provides three mechanisms:
- llm_fallback  : Multi-provider fallback chain for LLM calls
- db_retry      : Exponential backoff retry wrapper for database writes
- rate_limiter  : Token-bucket rate limiter for outbound API calls
"""

from krankenfahrt.resilience.db_retry import db_retry
from krankenfahrt.resilience.llm_fallback import call_with_fallback
from krankenfahrt.resilience.rate_limiter import TokenBucket, get_global_limiter

__all__ = ["call_with_fallback", "db_retry", "TokenBucket", "get_global_limiter"]
