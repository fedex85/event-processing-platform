"""Which ``occurred_at`` values the API accepts.

BigQuery only accepts streaming inserts into a partitioned table when the partition is within
31 days in the past and 16 days in the future of the current UTC date. An event outside that
range would be accepted by the API, then fail in the processor on every attempt and end up in
the dead-letter queue. Checking at the door lets the client fix the timestamp immediately.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from common.events import ErrorItem


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EventTimeWindow:
    max_age: timedelta
    max_future: timedelta
    # ``None`` means the real clock, looked up on every call so tests can replace it.
    clock: Callable[[], datetime] | None = None

    def check(self, occurred_at: datetime) -> ErrorItem | None:
        """An error item when ``occurred_at`` is outside the window, otherwise ``None``."""
        now = (self.clock or _utcnow)()
        if now - self.max_age <= occurred_at <= now + self.max_future:
            return None
        return ErrorItem(
            field="occurred_at",
            message=(
                f"must be within the last {self.max_age.days} days "
                f"and at most {self.max_future.days} days in the future"
            ),
        )
