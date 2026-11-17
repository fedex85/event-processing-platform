"""Retries with exponential backoff and full jitter."""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("delays must satisfy 0 <= base <= max")

    def delay_ceiling(self, attempt: int) -> float:
        """Upper bound of the wait after failed attempt number ``attempt`` (1-based)."""
        return min(self.max_delay_seconds, float(self.base_delay_seconds * 2 ** (attempt - 1)))


def call_with_retry[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    is_retryable: Callable[[Exception], bool],
    description: str,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> T:
    """Run ``operation``; retry retryable errors up to ``policy.attempts`` times in total.

    The wait is a random fraction (full jitter) of an exponentially growing
    ceiling, so many instances that fail together do not retry together.
    Non-retryable errors, and the last retryable one, propagate unchanged.
    """
    attempt = 1
    while True:
        try:
            return operation()
        except Exception as exc:
            if attempt >= policy.attempts or not is_retryable(exc):
                raise
            delay = jitter() * policy.delay_ceiling(attempt)
            logger.warning(
                "storage_retry",
                extra={
                    "operation": description,
                    "attempt": attempt,
                    "max_attempts": policy.attempts,
                    "retry_in_seconds": round(delay, 3),
                    "error_type": type(exc).__name__,
                },
            )
            sleep(delay)
            attempt += 1
