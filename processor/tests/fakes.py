"""Test doubles for the processor."""

from collections import deque
from collections.abc import Sequence
from datetime import timedelta

from common.events import IngestedStockEvent
from processor.domain.models import Alert, EventLookup
from processor.repositories.memory import InMemoryRepository


class ScriptedRepository(InMemoryRepository):
    """In-memory repository that can be told to fail on its next calls.

    ``fail("save_event", TransientStorageError("boom"))`` makes the next
    ``save_event`` call raise once; queue several to fail several times.
    """

    def __init__(self) -> None:
        super().__init__()
        self._failures: dict[str, deque[Exception]] = {}
        self.calls: list[str] = []

    def fail(self, method: str, *errors: Exception) -> None:
        self._failures.setdefault(method, deque()).extend(errors)

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        queue = self._failures.get(method)
        if queue:
            raise queue.popleft()

    def lookup(self, event: IngestedStockEvent, window: timedelta) -> EventLookup:
        self._maybe_fail("lookup")
        return super().lookup(event, window)

    def save_event(self, event: IngestedStockEvent) -> None:
        self._maybe_fail("save_event")
        super().save_event(event)

    def save_alerts(self, alerts: Sequence[Alert]) -> None:
        self._maybe_fail("save_alerts")
        super().save_alerts(alerts)
