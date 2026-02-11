"""Rate limiting using token bucket algorithm."""

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class RateLimitState:
    """State for a single rate limiter bucket."""
    tokens: float
    last_update: float


class RateLimiter:
    """Token bucket rate limiter.

    Allows burst traffic up to the limit, then enforces steady rate.
    """

    def __init__(self):
        """Initialize rate limiter."""
        self.buckets: dict[str, RateLimitState] = {}

    def check(self, key_id: str, limit: int) -> tuple[bool, float]:
        """Check if a request is allowed.

        Args:
            key_id: Identifier for this bucket (usually API key ID)
            limit: Requests per minute allowed

        Returns:
            (allowed, retry_after_seconds)
            - allowed: True if request can proceed
            - retry_after_seconds: How long to wait if denied (0 if allowed)
        """
        now = time.time()

        # Initialize bucket if first request
        if key_id not in self.buckets:
            self.buckets[key_id] = RateLimitState(tokens=limit, last_update=now)

        state = self.buckets[key_id]

        # Calculate time elapsed since last update
        elapsed = now - state.last_update

        # Refill tokens based on time elapsed
        # Tokens refill at rate of (limit / 60) per second
        refill_rate = limit / 60.0  # Tokens per second
        state.tokens = min(limit, state.tokens + (elapsed * refill_rate))
        state.last_update = now

        # Check if we have at least 1 token
        if state.tokens >= 1.0:
            state.tokens -= 1.0
            return True, 0.0

        # Calculate retry time (how long until 1 token available)
        tokens_needed = 1.0 - state.tokens
        retry_after = tokens_needed / refill_rate

        return False, retry_after

    def get_remaining(self, key_id: str, limit: int) -> int:
        """Get remaining requests in current window.

        Args:
            key_id: Identifier for this bucket
            limit: Requests per minute allowed

        Returns:
            Approximate number of requests remaining
        """
        state = self.buckets.get(key_id)
        if not state:
            return limit

        # Update tokens first
        now = time.time()
        elapsed = now - state.last_update
        refill_rate = limit / 60.0
        current_tokens = min(limit, state.tokens + (elapsed * refill_rate))

        return int(current_tokens)

    def reset(self, key_id: str):
        """Reset rate limit for a key (useful for testing or admin override).

        Args:
            key_id: Identifier to reset
        """
        if key_id in self.buckets:
            del self.buckets[key_id]

    def reset_all(self):
        """Reset all rate limiters."""
        self.buckets.clear()


class GlobalRateLimiter:
    """Rate limiter that tracks global limits across all keys."""

    def __init__(self, global_limit: int = 1000):
        """Initialize global rate limiter.

        Args:
            global_limit: Maximum requests per minute across all users
        """
        self.global_limit = global_limit
        self.limiter = RateLimiter()

    def check(self) -> tuple[bool, float]:
        """Check if a request is allowed globally.

        Returns:
            (allowed, retry_after_seconds)
        """
        return self.limiter.check("__global__", self.global_limit)

    def get_remaining(self) -> int:
        """Get remaining global requests.

        Returns:
            Approximate number of requests remaining
        """
        return self.limiter.get_remaining("__global__", self.global_limit)


class CombinedRateLimiter:
    """Combines per-key and global rate limiting."""

    def __init__(self, global_limit: int = 1000):
        """Initialize combined rate limiter.

        Args:
            global_limit: Maximum requests per minute globally
        """
        self.per_key_limiter = RateLimiter()
        self.global_limiter = GlobalRateLimiter(global_limit)

    def check(self, key_id: str, key_limit: int) -> tuple[bool, Optional[str], float]:
        """Check both per-key and global rate limits.

        Args:
            key_id: API key ID
            key_limit: Per-key limit (requests/minute)

        Returns:
            (allowed, reason_if_denied, retry_after_seconds)
        """
        # Check per-key limit first
        allowed, retry = self.per_key_limiter.check(key_id, key_limit)
        if not allowed:
            return False, "Per-key rate limit exceeded", retry

        # Check global limit
        allowed, retry = self.global_limiter.check()
        if not allowed:
            return False, "Global rate limit exceeded", retry

        return True, None, 0.0

    def get_stats(self, key_id: str, key_limit: int) -> dict:
        """Get rate limit statistics.

        Args:
            key_id: API key ID
            key_limit: Per-key limit

        Returns:
            Dict with remaining requests for key and global
        """
        return {
            "key_remaining": self.per_key_limiter.get_remaining(key_id, key_limit),
            "global_remaining": self.global_limiter.get_remaining(),
        }
