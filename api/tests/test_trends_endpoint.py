from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient

from api.errors.exceptions import AnalyticsUnavailableError
from api.tests.factories import make_trend_record
from api.tests.fakes import FakeAnalyticsRepository

URL = "/v1/metrics/stock-trends"


def get(client: FlaskClient, auth: dict[str, str], **params: str) -> Any:
    return client.get(URL, query_string=params, headers=auth)


def test_returns_hourly_aggregates(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.trends = [make_trend_record()]

    response = get(client, auth)

    assert response.status_code == 200
    body = response.get_json()
    assert body["granularity"] == "hour"
    assert body["items"] == [
        {
            "hour": "2026-11-16T19:00:00Z",
            "store_id": "store_014",
            "sku": "SKU-88231",
            "units_sold": 12,
            "units_restocked": 40,
            "avg_stock": 22.46,
            "event_count": 9,
            "stock_variation": 28,
        }
    ]
    assert body["pagination"] == {"limit": 100, "offset": 0, "returned": 1, "has_more": False}
    assert body["window"] == {"from": "2026-11-16T12:30:00Z", "to": None}


def test_buckets_without_stock_updates_report_null_stock_figures(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.trends = [make_trend_record(avg_stock=None, stock_variation=None)]

    [item] = get(client, auth).get_json()["items"]

    assert item["avg_stock"] is None
    assert item["stock_variation"] is None


def test_the_default_window_is_the_last_24_hours_aligned_to_the_hour(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(client, auth)

    [criteria] = analytics_repository.trend_filters
    assert criteria.start == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert criteria.end is None


def test_the_bucket_containing_from_is_included(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(client, auth, **{"from": "2026-11-16T19:45:00Z", "to": "2026-11-16T21:10:00Z"})

    [criteria] = analytics_repository.trend_filters
    assert criteria.start == datetime(2026, 11, 16, 19, 0, tzinfo=UTC)
    assert criteria.end == datetime(2026, 11, 16, 21, 10, tzinfo=UTC)


def test_filters_reach_the_repository(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(client, auth, store_id="store_014", sku="SKU-1", limit="5", offset="10")

    [criteria] = analytics_repository.trend_filters
    assert (criteria.store_id, criteria.sku, criteria.offset) == ("store_014", "SKU-1", 10)
    assert criteria.limit == 6  # one extra row to detect another page


def test_pagination(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.trends = [make_trend_record(sku=f"SKU-{i}") for i in range(3)]

    body = get(client, auth, limit="2").get_json()

    assert [t["sku"] for t in body["items"]] == ["SKU-0", "SKU-1"]
    assert body["pagination"]["has_more"] is True


def test_the_range_is_limited_to_31_days(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    response = get(client, auth, **{"from": "2026-10-01T00:00:00Z"})

    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        {"field": "from", "message": "the range must not exceed 31 days"}
    ]
    assert analytics_repository.trend_filters == []


def test_exactly_31_days_is_allowed(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth, **{"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("params", "field", "message"),
    [
        ({"limit": "1001"}, "limit", "must be an integer between 1 and 1000"),
        ({"limit": "0"}, "limit", "must be an integer between 1 and 1000"),
        ({"offset": "-5"}, "offset", "must be an integer between 0 and 100000"),
        ({"alert_type": "LOW_STOCK"}, "alert_type", "unknown parameter"),
        ({"store_id": ""}, "store_id", "must not be empty"),
    ],
)
def test_invalid_parameters_are_rejected(
    client: FlaskClient, auth: dict[str, str], params: dict[str, str], field: str, message: str
) -> None:
    response = get(client, auth, **params)

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "rejected",
        "errors": [{"field": field, "message": message}],
    }


def test_to_must_be_later_than_from(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth, **{"from": "2026-11-16T10:00:00Z", "to": "2026-11-16T09:00:00Z"})

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["field"] == "to"


def test_requires_an_api_key(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


def test_reads_share_the_clients_rate_limit(
    client: FlaskClient, auth: dict[str, str], settings: Any
) -> None:
    from api.app import create_app
    from api.config import ApiSettings
    from api.dependencies import build_dependencies
    from api.tests.fakes import FakeAnalyticsRepository, FakePublisher

    limited = ApiSettings(environment="local", api_keys="k", rate_limit_per_minute=2)
    app = create_app(
        limited,
        dependencies=build_dependencies(
            limited, publisher=FakePublisher(), analytics_repository=FakeAnalyticsRepository()
        ),
    )
    http = app.test_client()
    headers = {"X-API-Key": "k"}

    statuses = [http.get(URL, headers=headers).status_code for _ in range(3)]
    alerts_status = http.get("/v1/alerts", headers=headers).status_code

    assert statuses == [200, 200, 429]
    assert alerts_status == 429


def test_an_unavailable_store_is_a_503(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.error = AnalyticsUnavailableError()

    response = get(client, auth)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
