"""
Per-identity quotas and rate limits for consumer dashboard usage.
"""

import os
from mcp_network.security.ratelimit import RateLimiter

# Requests per minute per consumer (guest) identity
CONSUMER_RATE_LIMIT_PER_MINUTE = int(os.getenv("CONSUMER_RATE_LIMIT_PER_MINUTE", "60"))

_consumer_limiter = RateLimiter()


def check_consumer_rate_limit(consumer_identity: str) -> tuple[bool, float]:
    """Check if this consumer is within rate limit.

    Args:
        consumer_identity: From request.state.consumer_identity

    Returns:
        (allowed, retry_after_seconds). retry_after is 0 if allowed.
    """
    return _consumer_limiter.check(consumer_identity, CONSUMER_RATE_LIMIT_PER_MINUTE)
