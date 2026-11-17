from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient

from api.errors.exceptions import AnalyticsQueryError, AnalyticsUnavailableError
from api.tests.factories import make_alert_record
from api.tests.fakes import FakeAnalyticsRepository
from common.alerts import AlertStatus, AlertType, Severity

URL = "/v1/alerts"


def get(client: FlaskClient, auth: dict[str, str], **params: str) -> Any:
    return client.get(URL, query_string=params, headers=auth)


# --- success and shape ---


def test_returns_alerts_with_pagination_and_window(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.alerts = [make_alert_record()]

    response = get(client, auth)

    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == [
        {
            "alert_id": "alert-1",
            "event_id": "evt_01J5Z8K9Q2M7",
            "store_id": "store_014",
            "sku": "SKU-88231",
            "alert_type": "LOW_STOCK",
            "severity": "MEDIUM",
            "detected_at": "2026-11-16T19:40:13Z",
            "details": {"quantity": 3, "threshold": 5, "unit": "units"},
            "status": "OPEN",
        }
    ]
    assert body["pagination"] == {"limit": 50, "offset": 0, "returned": 1, "has_more": False}
    assert body["window"] == {"from": "2026-11-10T12:30:00Z", "to": None}


def test_an_empty_result_is_a_normal_answer(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth)

    assert response.status_code == 200
    assert response.get_json()["items"] == []


def test_the_default_window_is_the_last_seven_days(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(client, auth)

    [criteria] = analytics_repository.alert_filters
    assert criteria.start == datetime(2026, 11, 10, 12, 30, tzinfo=UTC)
    assert criteria.end is None


def test_filters_reach_the_repository(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(
        client,
        auth,
        store_id="store_014",
        sku="SKU-1",
        alert_type="OUT_OF_STOCK",
        severity="CRITICAL",
        status="OPEN",
        **{"from": "2026-11-16T00:00:00Z", "to": "2026-11-17T00:00:00Z"},
        limit="10",
        offset="20",
    )

    [criteria] = analytics_repository.alert_filters
    assert criteria.store_id == "store_014"
    assert criteria.sku == "SKU-1"
    assert criteria.alert_type is AlertType.OUT_OF_STOCK
    assert criteria.severity is Severity.CRITICAL
    assert criteria.status is AlertStatus.OPEN
    assert criteria.start == datetime(2026, 11, 16, tzinfo=UTC)
    assert criteria.end == datetime(2026, 11, 17, tzinfo=UTC)
    assert criteria.offset == 20


def test_timestamps_with_an_offset_are_converted_to_utc(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    response = get(client, auth, **{"from": "2026-11-16T01:00:00+01:00"})

    assert response.status_code == 200
    assert analytics_repository.alert_filters[0].start == datetime(2026, 11, 16, tzinfo=UTC)
    assert response.get_json()["window"]["from"] == "2026-11-16T00:00:00Z"


# --- pagination ---


def test_has_more_is_true_when_another_page_exists(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.alerts = [make_alert_record(alert_id=f"a{i}") for i in range(5)]

    body = get(client, auth, limit="2").get_json()

    assert [a["alert_id"] for a in body["items"]] == ["a0", "a1"]
    assert body["pagination"] == {"limit": 2, "offset": 0, "returned": 2, "has_more": True}


def test_the_last_page_has_no_more(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.alerts = [make_alert_record(alert_id=f"a{i}") for i in range(5)]

    body = get(client, auth, limit="2", offset="4").get_json()

    assert [a["alert_id"] for a in body["items"]] == ["a4"]
    assert body["pagination"]["has_more"] is False


def test_exactly_a_full_page_has_no_more(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.alerts = [make_alert_record(alert_id=f"a{i}") for i in range(2)]

    assert get(client, auth, limit="2").get_json()["pagination"]["has_more"] is False


def test_the_repository_is_asked_for_one_extra_row(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    get(client, auth, limit="7")

    assert analytics_repository.alert_filters[0].limit == 8


# --- validation ---


@pytest.mark.parametrize(
    ("params", "field", "message"),
    [
        (
            {"alert_type": "NOPE"},
            "alert_type",
            "must be one of: LOW_STOCK, OUT_OF_STOCK, RAPID_STOCK_DROP",
        ),
        ({"severity": "urgent"}, "severity", "must be one of: LOW, MEDIUM, HIGH, CRITICAL"),
        ({"status": "closed"}, "status", "must be one of: OPEN"),
        ({"limit": "0"}, "limit", "must be an integer between 1 and 500"),
        ({"limit": "501"}, "limit", "must be an integer between 1 and 500"),
        ({"limit": "ten"}, "limit", "must be an integer between 1 and 500"),
        ({"limit": "2.5"}, "limit", "must be an integer between 1 and 500"),
        ({"offset": "-1"}, "offset", "must be an integer between 0 and 100000"),
        ({"offset": "100001"}, "offset", "must be an integer between 0 and 100000"),
        ({"store_id": ""}, "store_id", "must not be empty"),
        ({"sku": "x" * 256}, "sku", "must be at most 255 characters"),
        ({"colour": "red"}, "colour", "unknown parameter"),
    ],
)
def test_invalid_parameters_are_rejected_with_the_field_name(
    client: FlaskClient,
    auth: dict[str, str],
    analytics_repository: FakeAnalyticsRepository,
    params: dict[str, str],
    field: str,
    message: str,
) -> None:
    response = get(client, auth, **params)

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "rejected",
        "errors": [{"field": field, "message": message}],
    }
    assert analytics_repository.alert_filters == []


@pytest.mark.parametrize("value", ["yesterday", "2026-11-16", "1700000000", "2026-13-45T00:00:00Z"])
def test_malformed_timestamps_are_rejected(
    client: FlaskClient, auth: dict[str, str], value: str
) -> None:
    response = get(client, auth, **{"from": value})

    assert response.status_code == 400
    [error] = response.get_json()["errors"]
    assert error["field"] == "from"
    assert "ISO 8601" in error["message"]


def test_a_timestamp_without_a_timezone_is_rejected(
    client: FlaskClient, auth: dict[str, str]
) -> None:
    response = get(client, auth, to="2026-11-16T19:40:12")

    [error] = response.get_json()["errors"]
    assert error["field"] == "to"
    assert "timezone" in error["message"]


def test_a_repeated_parameter_is_rejected(client: FlaskClient, auth: dict[str, str]) -> None:
    response = client.get(f"{URL}?sku=a&sku=b", headers=auth)

    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        {"field": "sku", "message": "must be provided only once"}
    ]


def test_every_problem_is_reported_at_once(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth, limit="0", severity="x", extra="1")

    fields = {e["field"] for e in response.get_json()["errors"]}
    assert fields == {"limit", "severity", "extra"}


def test_to_must_be_later_than_from(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth, **{"from": "2026-11-16T00:00:00Z", "to": "2026-11-16T00:00:00Z"})

    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        {"field": "to", "message": "must be later than 'from'"}
    ]


def test_rejections_never_echo_the_value(client: FlaskClient, auth: dict[str, str]) -> None:
    response = get(client, auth, limit="secret-value")

    assert "secret-value" not in response.get_data(as_text=True)


# --- security ---


def test_requires_an_api_key(client: FlaskClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.get_json()["code"] == "unauthorized"


def test_a_wrong_api_key_is_rejected(client: FlaskClient) -> None:
    assert client.get(URL, headers={"X-API-Key": "nope"}).status_code == 401


def test_an_unauthenticated_request_does_not_reach_the_repository(
    client: FlaskClient, analytics_repository: FakeAnalyticsRepository
) -> None:
    client.get(URL)

    assert analytics_repository.alert_filters == []


def test_only_get_is_allowed(client: FlaskClient, auth: dict[str, str]) -> None:
    assert client.post(URL, headers=auth, json={}).status_code == 405


# --- failures ---


def test_an_unavailable_store_is_a_503_with_retry_after(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.error = AnalyticsUnavailableError()

    response = get(client, auth)

    assert response.status_code == 503
    assert response.get_json()["code"] == "analytics_unavailable"
    assert response.headers["Retry-After"] == "5"


def test_a_failed_query_is_a_500_without_details(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.error = AnalyticsQueryError()

    response = get(client, auth)

    assert response.status_code == 500
    assert response.get_json()["code"] == "analytics_error"


def test_an_unexpected_error_does_not_leak(
    client: FlaskClient, auth: dict[str, str], analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.error = RuntimeError("internal secret")

    response = get(client, auth)

    assert response.status_code == 500
    assert "internal secret" not in response.get_data(as_text=True)
