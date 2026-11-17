from datetime import UTC, datetime

import pytest

from api.errors.exceptions import AnalyticsQueryError, AnalyticsUnavailableError
from api.repositories.base import AlertFilter, TrendFilter
from api.repositories.bigquery import BigQueryAnalyticsRepository
from common.alerts import AlertStatus, AlertType, Severity
from common.retry import RetryPolicy
from common.tests.fakes import FakeGateway, HttpError

START = datetime(2026, 11, 10, 12, 30, tzinfo=UTC)
END = datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
DETECTED = datetime(2026, 11, 16, 19, 40, 13, tzinfo=UTC)


def make_repo(
    gateway: FakeGateway, sleeps: list[float] | None = None
) -> BigQueryAnalyticsRepository:
    return BigQueryAnalyticsRepository(
        gateway,
        project_id="my-project",
        dataset="inventory_analytics",
        alerts_table="stock_alerts",
        trends_view="v_stock_trends",
        retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0.1, max_delay_seconds=0.2),
        timeout_seconds=8.0,
        sleep=(sleeps if sleeps is not None else []).append,
    )


def alert_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "alert_id": "a1",
        "event_id": "e1",
        "store_id": "s1",
        "sku": "k1",
        "alert_type": "LOW_STOCK",
        "severity": "MEDIUM",
        "detected_at": DETECTED,
        "details": '{"quantity": 3}',
        "status": "OPEN",
    }
    row.update(overrides)
    return row


def trend_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "hour_start": datetime(2026, 11, 16, 19, tzinfo=UTC),
        "store_id": "s1",
        "sku": "k1",
        "units_sold": 4,
        "units_restocked": 0,
        "avg_stock": 17.5,
        "event_count": 6,
        "stock_variation": -4,
    }
    row.update(overrides)
    return row


# --- alerts: SQL and parameters ---


def test_alerts_query_the_alerts_table_with_a_lower_bound_only() -> None:
    gateway = FakeGateway()

    make_repo(gateway).find_alerts(AlertFilter(start=START, limit=51, offset=0))

    sql, params, timeout = gateway.queries[0]
    assert "FROM `my-project.inventory_analytics.stock_alerts`" in sql
    assert "detected_at >= @start" in sql
    assert "@end" not in sql
    assert "ORDER BY detected_at DESC, alert_id" in sql
    assert "LIMIT @limit OFFSET @offset" in sql
    assert params == {
        "start": ("TIMESTAMP", START),
        "limit": ("INT64", 51),
        "offset": ("INT64", 0),
    }
    assert timeout == 8.0


def test_alerts_deduplicate_by_alert_id_after_the_time_filter() -> None:
    gateway = FakeGateway()

    make_repo(gateway).find_alerts(AlertFilter(start=START, limit=1, offset=0))

    sql = gateway.queries[0][0]
    assert sql.index("WHERE") < sql.index("QUALIFY ROW_NUMBER() OVER (PARTITION BY alert_id")


def test_alerts_add_only_the_filters_that_were_given() -> None:
    gateway = FakeGateway()

    make_repo(gateway).find_alerts(
        AlertFilter(
            start=START,
            end=END,
            store_id="store_014",
            sku="SKU-1",
            alert_type=AlertType.RAPID_STOCK_DROP,
            severity=Severity.HIGH,
            status=AlertStatus.OPEN,
            limit=10,
            offset=20,
        )
    )

    sql, params, _ = gateway.queries[0]
    for clause in (
        "detected_at < @end",
        "store_id = @store_id",
        "sku = @sku",
        "alert_type = @alert_type",
        "severity = @severity",
        "status = @status",
    ):
        assert clause in sql
    assert params["end"] == ("TIMESTAMP", END)
    assert params["store_id"] == ("STRING", "store_014")
    assert params["alert_type"] == ("STRING", "RAPID_STOCK_DROP")
    assert params["severity"] == ("STRING", "HIGH")
    assert params["status"] == ("STRING", "OPEN")
    assert params["offset"] == ("INT64", 20)


def test_client_values_never_appear_in_the_sql() -> None:
    gateway = FakeGateway()
    hostile = "x'; DROP TABLE stock_alerts; --"

    make_repo(gateway).find_alerts(
        AlertFilter(start=START, store_id=hostile, sku=hostile, limit=1, offset=0)
    )

    sql, params, _ = gateway.queries[0]
    assert "DROP TABLE" not in sql
    assert params["store_id"] == ("STRING", hostile)


# --- alerts: rows ---


def test_alert_rows_become_records_with_decoded_details() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([alert_row()])

    [record] = make_repo(gateway).find_alerts(AlertFilter(start=START, limit=1, offset=0))

    assert record.alert_id == "a1"
    assert record.alert_type == "LOW_STOCK"
    assert record.detected_at == DETECTED
    assert record.details == {"quantity": 3}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"already": "decoded"}, {"already": "decoded"}),
        (None, {}),
        ("", {}),
        ("not json", {}),
        ("[1, 2]", {}),
        ("42", {}),
    ],
)
def test_details_that_are_not_a_json_object_become_an_empty_object(
    raw: object, expected: dict[str, object]
) -> None:
    gateway = FakeGateway()
    gateway.query_results.append([alert_row(details=raw)])

    [record] = make_repo(gateway).find_alerts(AlertFilter(start=START, limit=1, offset=0))

    assert record.details == expected


# --- trends ---


def test_trends_query_the_view_ordered_newest_first() -> None:
    gateway = FakeGateway()

    make_repo(gateway).find_trends(TrendFilter(start=START, limit=101, offset=0))

    sql, params, _ = gateway.queries[0]
    assert "FROM `my-project.inventory_analytics.v_stock_trends`" in sql
    assert "hour_start >= @start" in sql
    assert "ORDER BY hour_start DESC, store_id, sku" in sql
    assert set(params) == {"start", "limit", "offset"}


def test_trends_add_only_the_filters_that_were_given() -> None:
    gateway = FakeGateway()

    make_repo(gateway).find_trends(
        TrendFilter(start=START, end=END, store_id="s1", sku="k1", limit=5, offset=5)
    )

    sql, params, _ = gateway.queries[0]
    assert "hour_start < @end" in sql
    assert "store_id = @store_id" in sql
    assert "sku = @sku" in sql
    assert params["sku"] == ("STRING", "k1")


def test_trend_rows_become_records() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([trend_row()])

    [record] = make_repo(gateway).find_trends(TrendFilter(start=START, limit=1, offset=0))

    assert record.units_sold == 4
    assert record.avg_stock == 17.5
    assert record.stock_variation == -4
    assert record.event_count == 6


def test_missing_figures_are_kept_distinct_from_zero() -> None:
    gateway = FakeGateway()
    gateway.query_results.append(
        [trend_row(units_sold=None, units_restocked=None, avg_stock=None, stock_variation=None)]
    )

    [record] = make_repo(gateway).find_trends(TrendFilter(start=START, limit=1, offset=0))

    assert (record.units_sold, record.units_restocked) == (0, 0)
    assert record.avg_stock is None
    assert record.stock_variation is None


# --- failures ---


def test_a_transient_failure_is_retried() -> None:
    gateway = FakeGateway()
    gateway.query_results.extend([HttpError(503), [alert_row()]])
    sleeps: list[float] = []

    records = make_repo(gateway, sleeps).find_alerts(AlertFilter(start=START, limit=1, offset=0))

    assert len(records) == 1
    assert len(gateway.queries) == 2
    assert len(sleeps) == 1


def test_a_transient_failure_that_persists_becomes_a_503() -> None:
    gateway = FakeGateway()
    gateway.query_results.extend([HttpError(503), HttpError(503)])

    with pytest.raises(AnalyticsUnavailableError):
        make_repo(gateway).find_alerts(AlertFilter(start=START, limit=1, offset=0))

    assert len(gateway.queries) == 2


def test_a_permanent_failure_is_not_retried_and_becomes_a_500() -> None:
    gateway = FakeGateway()
    gateway.query_results.append(HttpError(403, "Access Denied: secret-detail"))

    with pytest.raises(AnalyticsQueryError) as caught:
        make_repo(gateway).find_trends(TrendFilter(start=START, limit=1, offset=0))

    assert len(gateway.queries) == 1
    assert "secret-detail" not in str(caught.value)


def test_a_bug_in_the_row_mapping_is_not_reported_as_unavailability() -> None:
    gateway = FakeGateway()
    gateway.query_results.append([{"alert_id": "a1"}])  # columns missing

    with pytest.raises(KeyError):
        make_repo(gateway).find_alerts(AlertFilter(start=START, limit=1, offset=0))


# --- construction and formatting ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": "BAD PROJECT"},
        {"dataset": "data`set"},
        {"alerts_table": "a.b"},
        {"trends_view": ""},
    ],
)
def test_rejects_identifiers_that_could_break_the_sql(overrides: dict[str, str]) -> None:
    names = {
        "project_id": "my-project",
        "dataset": "inventory_analytics",
        "alerts_table": "stock_alerts",
        "trends_view": "v_stock_trends",
        **overrides,
    }

    with pytest.raises(ValueError, match="invalid BigQuery"):
        BigQueryAnalyticsRepository(
            FakeGateway(),
            project_id=names["project_id"],
            dataset=names["dataset"],
            alerts_table=names["alerts_table"],
            trends_view=names["trends_view"],
            retry_policy=RetryPolicy(),
            timeout_seconds=1.0,
        )
