from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last: float


class RateLimiter:
    """In-memory token bucket (MVP). Replace with Redis for production."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def allow(self, key: str, capacity: int = 30, refill_per_sec: float = 1.0) -> bool:
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

        # refill
        elapsed = now - bucket.last
        bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_sec)
        bucket.last = now

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True

        return False

