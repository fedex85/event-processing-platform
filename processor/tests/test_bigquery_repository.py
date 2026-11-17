import json
from datetime import timedelta

import pytest

from processor.domain.errors import PermanentStorageError, TransientStorageError
from processor.domain.models import AlertType
from processor.repositories.bigquery import (
    BigQueryRepository,
    classify_row_errors,
    is_transient_exception,
)
from processor.repositories.retry import RetryPolicy
from processor.rules import evaluate_rules
from processor.tests.factories import OCCURRED_AT, make_context, make_event
from processor.tests.fakes import FakeGateway, HttpError

WINDOW = timedelta(minutes=15)


def make_repo(gateway: FakeGateway, sleeps: list[float] | None = None) -> BigQueryRepository:
    return BigQueryRepository(
        gateway,
        project_id="my-project",
        dataset="inventory_analytics",
        events_table="stock_events",
        alerts_table="stock_alerts",
        retry_policy=RetryPolicy(attempts=3, base_delay_seconds=0.1, max_delay_seconds=0.2),
        timeout_seconds=5.0,
        sleep=(sleeps if sleeps is not None else []).append,
    )


def row_error(*reasons: str) -> list[dict[str, object]]:
    return [
        {"index": 0, "errors": [{"reason": r, "location": "x", "message": "m"} for r in reasons]}
    ]


# --- lookup ---


def test_lookup_runs_one_parameterised_query_scoped_to_the_window() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([{"seen": 0, "recent_max_quantity": None}])

    make_repo(gateway).lookup(make_event(), WINDOW)

    assert len(gateway.queries) == 1
    sql, params, timeout = gateway.queries[0]
    assert "`my-project.inventory_analytics.stock_events`" in sql
    assert "occurred_at BETWEEN @window_start AND @occurred_at" in sql
    assert params["event_id"] == ("STRING", "evt_01J5Z8K9Q2M7")
    assert params["store_id"] == ("STRING", "store_014")
    assert params["sku"] == ("STRING", "SKU-88231")
    assert params["occurred_at"] == ("TIMESTAMP", OCCURRED_AT)
    assert params["window_start"] == ("TIMESTAMP", OCCURRED_AT - WINDOW)
    assert timeout == 5.0


def test_lookup_never_interpolates_event_values_into_the_sql() -> None:
    gateway = FakeGateway()
    event = make_event(store_id="x'; DROP TABLE stock_events; --")

    make_repo(gateway).lookup(event, WINDOW)

    assert "DROP TABLE" not in gateway.queries[0][0]


def test_lookup_reads_a_duplicate_and_the_history() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([{"seen": 1, "recent_max_quantity": 42}])

    lookup = make_repo(gateway).lookup(make_event(), WINDOW)

    assert lookup.is_duplicate is True
    assert lookup.recent_max_quantity == 42


def test_lookup_handles_no_history() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([{"seen": 0, "recent_max_quantity": None}])

    lookup = make_repo(gateway).lookup(make_event(), WINDOW)

    assert lookup.is_duplicate is False
    assert lookup.recent_max_quantity is None


def test_lookup_handles_an_empty_result() -> None:
    lookup = make_repo(FakeGateway()).lookup(make_event(), WINDOW)

    assert lookup.is_duplicate is False
    assert lookup.recent_max_quantity is None


def test_lookup_retries_transient_failures() -> None:
    gateway = FakeGateway()
    gateway.query_results.extend([HttpError(503), [{"seen": 0, "recent_max_quantity": 7}]])
    sleeps: list[float] = []

    lookup = make_repo(gateway, sleeps).lookup(make_event(), WINDOW)

    assert lookup.recent_max_quantity == 7
    assert len(gateway.queries) == 2
    assert len(sleeps) == 1


def test_lookup_gives_up_with_a_transient_error_after_the_last_attempt() -> None:
    gateway = FakeGateway()
    gateway.query_results.extend([HttpError(503)] * 3)

    with pytest.raises(TransientStorageError, match="HttpError"):
        make_repo(gateway).lookup(make_event(), WINDOW)

    assert len(gateway.queries) == 3


def test_lookup_does_not_retry_a_permanent_failure() -> None:
    gateway = FakeGateway()
    gateway.query_results.append(HttpError(403, "denied"))

    with pytest.raises(PermanentStorageError):
        make_repo(gateway).lookup(make_event(), WINDOW)

    assert len(gateway.queries) == 1


# --- save_event ---


def test_save_event_writes_one_row_with_the_event_id_as_insert_id() -> None:
    gateway = FakeGateway()

    make_repo(gateway).save_event(make_event(event_id="evt_1", quantity=7, previous_quantity=None))

    table, rows, row_ids, timeout = gateway.inserts[0]
    assert table == "my-project.inventory_analytics.stock_events"
    assert row_ids == ["evt_1"]
    assert timeout == 5.0
    row = rows[0]
    assert row["event_id"] == "evt_1"
    assert row["event_type"] == "STOCK_UPDATED"
    assert row["quantity"] == 7
    assert row["previous_quantity"] is None
    assert row["processing_status"] == "PROCESSED"
    assert row["occurred_at"] == "2026-11-16T19:40:12+00:00"
    assert row["ingested_at"] == "2026-11-16T19:40:13+00:00"
    assert json.loads(str(row["metadata"])) == {"region": "asturias", "channel": "physical_store"}


def test_save_event_keeps_non_ascii_metadata_readable() -> None:
    gateway = FakeGateway()

    make_repo(gateway).save_event(make_event(metadata={"city": "Gijón"}))

    assert "Gijón" in str(gateway.inserts[0][1][0]["metadata"])


def test_save_event_retries_a_transient_api_error_with_the_same_insert_id() -> None:
    gateway = FakeGateway()
    gateway.insert_results.extend([HttpError(503), []])

    make_repo(gateway).save_event(make_event())

    assert len(gateway.inserts) == 2
    assert gateway.inserts[0][2] == gateway.inserts[1][2]


def test_save_event_retries_transient_row_errors() -> None:
    gateway = FakeGateway()
    gateway.insert_results.extend([row_error("backendError"), []])

    make_repo(gateway).save_event(make_event())

    assert len(gateway.inserts) == 2


def test_save_event_fails_permanently_on_a_schema_error_without_retrying() -> None:
    gateway = FakeGateway()
    gateway.insert_results.append(row_error("invalid"))

    with pytest.raises(PermanentStorageError, match="invalid"):
        make_repo(gateway).save_event(make_event())

    assert len(gateway.inserts) == 1


def test_save_event_gives_up_after_repeated_transient_failures() -> None:
    gateway = FakeGateway()
    gateway.insert_results.extend([row_error("internalError")] * 3)
    sleeps: list[float] = []

    with pytest.raises(TransientStorageError):
        make_repo(gateway, sleeps).save_event(make_event())

    assert len(gateway.inserts) == 3
    assert len(sleeps) == 2


# --- save_alerts ---


def test_save_alerts_writes_all_alerts_in_one_call_using_alert_ids_as_insert_ids() -> None:
    gateway = FakeGateway()
    alerts = evaluate_rules(make_event(quantity=0, previous_quantity=20), make_context())

    make_repo(gateway).save_alerts(alerts)

    assert len(gateway.inserts) == 1
    table, rows, row_ids, _ = gateway.inserts[0]
    assert table == "my-project.inventory_analytics.stock_alerts"
    assert row_ids == [a.alert_id for a in alerts]
    assert {r["alert_type"] for r in rows} == {
        AlertType.OUT_OF_STOCK.value,
        AlertType.RAPID_STOCK_DROP.value,
    }
    details = json.loads(str(rows[0]["details"]))
    assert isinstance(details, dict)
    assert rows[0]["status"] == "OPEN"


def test_save_alerts_with_nothing_to_save_does_not_call_bigquery() -> None:
    gateway = FakeGateway()

    make_repo(gateway).save_alerts([])

    assert gateway.inserts == []


# --- classification ---


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_http_codes(code: int) -> None:
    assert is_transient_exception(HttpError(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409])
def test_permanent_http_codes(code: int) -> None:
    assert is_transient_exception(HttpError(code)) is False


def test_network_trouble_is_transient() -> None:
    assert is_transient_exception(TimeoutError()) is True
    assert is_transient_exception(ConnectionResetError()) is True


def test_local_file_problems_and_programming_errors_are_not_transient() -> None:
    assert is_transient_exception(FileNotFoundError()) is False
    assert is_transient_exception(PermissionError()) is False
    assert is_transient_exception(ValueError("bug")) is False


def test_row_errors_are_transient_only_when_every_reason_is() -> None:
    assert isinstance(classify_row_errors(row_error("backendError")), TransientStorageError)
    assert isinstance(
        classify_row_errors(row_error("backendError", "stopped")), TransientStorageError
    )
    assert isinstance(classify_row_errors(row_error("invalid", "stopped")), PermanentStorageError)
    assert isinstance(
        classify_row_errors(row_error("backendError", "invalid")), PermanentStorageError
    )


# --- construction ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": "BAD PROJECT"},
        {"dataset": "data`set"},
        {"events_table": "stock-events"},
        {"alerts_table": "a.b"},
        {"dataset": ""},
    ],
)
def test_rejects_identifiers_that_could_break_the_sql(overrides: dict[str, str]) -> None:
    names = {
        "project_id": "my-project",
        "dataset": "inventory_analytics",
        "events_table": "stock_events",
        "alerts_table": "stock_alerts",
        **overrides,
    }

    with pytest.raises(ValueError, match="invalid BigQuery"):
        BigQueryRepository(
            FakeGateway(),
            project_id=names["project_id"],
            dataset=names["dataset"],
            events_table=names["events_table"],
            alerts_table=names["alerts_table"],
            retry_policy=RetryPolicy(),
            timeout_seconds=1.0,
        )
