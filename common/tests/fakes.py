"""Test doubles shared by the service test suites."""

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from common.bigquery import QueryParam, RowErrors


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
