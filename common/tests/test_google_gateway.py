"""Checks how the gateway talks to the Google client. Skipped when the library is not installed."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("google.cloud.bigquery")

from common.bigquery import GoogleBigQueryGateway


class FakeRow:
    def __init__(self, **values: Any) -> None:
        self._values = values

    def items(self) -> Iterator[tuple[str, Any]]:
        return iter(self._values.items())


class FakeJob:
    def __init__(self, rows: list[FakeRow]) -> None:
        self._rows = rows
        self.result_timeout: float | None = None

    def result(self, *, timeout: float) -> list[FakeRow]:
        self.result_timeout = timeout
        return self._rows


class FakeClient:
    def __init__(self) -> None:
        self.job = FakeJob([FakeRow(seen=1, recent_max_quantity=9)])
        self.query_call: dict[str, Any] = {}
        self.insert_call: dict[str, Any] = {}

    def query(self, sql: str, *, job_config: Any, timeout: float) -> FakeJob:
        self.query_call = {"sql": sql, "job_config": job_config, "timeout": timeout}
        return self.job

    def insert_rows_json(
        self, table: str, rows: list[Any], *, row_ids: list[str], timeout: float
    ) -> list[Any]:
        self.insert_call = {"table": table, "rows": rows, "row_ids": row_ids, "timeout": timeout}
        return [{"index": 0, "errors": [{"reason": "invalid"}]}]


def test_query_rows_sends_named_typed_parameters_and_returns_plain_dicts() -> None:
    client = FakeClient()
    moment = datetime(2026, 11, 16, tzinfo=UTC)

    rows = GoogleBigQueryGateway(client).query_rows(
        "SELECT 1", {"sku": ("STRING", "A"), "at": ("TIMESTAMP", moment)}, timeout_seconds=4.0
    )

    assert rows == [{"seen": 1, "recent_max_quantity": 9}]
    params = client.query_call["job_config"].query_parameters
    assert [(p.name, p.value) for p in params] == [("sku", "A"), ("at", moment)]
    assert client.query_call["timeout"] == 4.0
    assert client.job.result_timeout == 4.0


def test_insert_rows_passes_row_ids_and_returns_the_row_errors() -> None:
    client = FakeClient()

    errors = GoogleBigQueryGateway(client).insert_rows(
        "p.d.t", [{"a": 1}], ["id-1"], timeout_seconds=3.0
    )

    assert client.insert_call == {
        "table": "p.d.t",
        "rows": [{"a": 1}],
        "row_ids": ["id-1"],
        "timeout": 3.0,
    }
    assert errors == [{"index": 0, "errors": [{"reason": "invalid"}]}]


def test_queries_carry_the_bytes_billed_cap() -> None:
    client = FakeClient()

    GoogleBigQueryGateway(client, maximum_bytes_billed=123_000_000).query_rows(
        "SELECT 1", {}, timeout_seconds=1.0
    )

    assert client.query_call["job_config"].maximum_bytes_billed == 123_000_000


def test_without_a_cap_the_job_config_has_none() -> None:
    client = FakeClient()

    GoogleBigQueryGateway(client).query_rows("SELECT 1", {}, timeout_seconds=1.0)

    assert client.query_call["job_config"].maximum_bytes_billed is None
