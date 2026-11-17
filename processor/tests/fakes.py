"""Test doubles for the processor."""

from collections import deque
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from common.events import IngestedStockEvent
from processor.domain.models import Alert, EventLookup
from processor.repositories.bigquery import QueryParam, RowErrors
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


class FakeGateway:
    """Records BigQuery calls and replays scripted answers.

    Each queue entry is either a result or an exception to raise. When a queue
    is empty, queries return no rows and inserts report no errors.
    """

    def __init__(self) -> None:
        self.query_results: deque[list[Mapping[str, Any]] | Exception] = deque()
        self.insert_results: deque[RowErrors | Exception] = deque()
        self.queries: list[tuple[str, dict[str, QueryParam], float]] = []
        self.inserts: list[tuple[str, list[Mapping[str, Any]], list[str], float]] = []

    def query_rows(
        self, sql: str, parameters: Mapping[str, QueryParam], *, timeout_seconds: float
    ) -> list[Mapping[str, Any]]:
        self.queries.append((sql, dict(parameters), timeout_seconds))
        result = self.query_results.popleft() if self.query_results else []
        if isinstance(result, Exception):
            raise result
        return result

    def insert_rows(
        self,
        table: str,
        rows: Sequence[Mapping[str, Any]],
        row_ids: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RowErrors:
        self.inserts.append((table, list(rows), list(row_ids), timeout_seconds))
        result = self.insert_results.popleft() if self.insert_results else []
        if isinstance(result, Exception):
            raise result
        return result


class HttpError(Exception):
    """Stands in for google.api_core exceptions, which expose the HTTP status as ``code``."""

    def __init__(self, code: int, message: str = "error") -> None:
        super().__init__(message)
        self.code = code
