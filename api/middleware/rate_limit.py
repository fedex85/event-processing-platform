"""Basic rate limiting."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    """Token bucket per client, held in memory.

    The bucket holds one minute of requests and refills continuously. Limits are
    per process: with several Cloud Run instances the effective limit is
    ``rate_per_minute`` times the number of instances, so it is a safety net
    against runaway clients rather than an exact quota.
    """

    def __init__(
        self,
        rate_per_minute: int,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = float(rate_per_minute)
        self._refill_per_second = rate_per_minute / 60
        self._monotonic = monotonic
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, client_id: str) -> float:
        """Take one token. Returns 0 when allowed, otherwise the seconds to wait."""
        now = self._monotonic()
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                bucket = self._buckets[client_id] = _Bucket(self._capacity, now)
            else:
                elapsed = now - bucket.updated_at
                bucket.tokens = min(
                    self._capacity, bucket.tokens + elapsed * self._refill_per_second
                )
                bucket.updated_at = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return 0.0
            return (1 - bucket.tokens) / self._refill_per_second
