from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last: float


class RateLimiterAdvanced:
    """In-memory rate limiter with burst control (token bucket).

    This is MVP-only; replace with Redis in production for multi-instance.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def allow(
        self,
        key: str,
        *,
        capacity: int,
        refill_per_sec: float,
    ) -> bool:
        """Return True if request is allowed, else False."""

        if capacity <= 0:
            return False

        now = time.time()
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = TokenBucket(
                capacity=capacity,
                refill_per_sec=refill_per_sec,
                tokens=float(capacity),
                last=now,
            )
            return True

        elapsed = now - bucket.last
        if elapsed > 0:
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_sec)
            bucket.last = now

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True

        return False


def _per_window_to_bucket(window_seconds: float, limit: int) -> tuple[int, float]:
    """Convert a limit-per-window to (capacity, refill_per_sec) for token bucket."""
    if window_seconds <= 0:
        raise ValueError("window_seconds must be > 0")
    if limit <= 0:
        raise ValueError("limit must be > 0")
    # Use burst-capacity == limit and refill == limit/window
    capacity = int(limit)
    refill_per_sec = float(limit) / float(window_seconds)
    return capacity, refill_per_sec


def make_burst_controller(limit: int, window_seconds: float) -> tuple[int, float]:
    """Helper to define bucket params for a burst/sustained limit."""
    return _per_window_to_bucket(window_seconds, limit)

