from datetime import UTC, datetime, timedelta

import pytest

from api.query_params import AlertQuery, TrendQuery
from api.services.analytics import AnalyticsService
from api.tests.factories import NOW, make_alert_record
from api.tests.fakes import FakeAnalyticsRepository
from common.errors import RejectedError


@pytest.fixture
def service(analytics_repository: FakeAnalyticsRepository) -> AnalyticsService:
    return AnalyticsService(analytics_repository, clock=lambda: NOW)


def at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def test_alerts_use_the_configured_default_lookback(
    analytics_repository: FakeAnalyticsRepository,
) -> None:
    service = AnalyticsService(
        analytics_repository, alerts_lookback=timedelta(days=2), clock=lambda: NOW
    )

    page = service.list_alerts(AlertQuery())

    assert page.window.start == NOW - timedelta(days=2)
    assert page.window.end is None


def test_an_explicit_window_is_kept(service: AnalyticsService) -> None:
    page = service.list_alerts(AlertQuery.model_validate({"from": "2026-11-01T00:00:00Z"}))

    assert page.window.start == at(1)


def test_alerts_have_no_range_limit(service: AnalyticsService) -> None:
    page = service.list_alerts(AlertQuery.model_validate({"from": "2020-01-01T00:00:00Z"}))

    assert page.window.start.year == 2020


def test_trends_floor_the_start_to_the_hour_but_report_the_requested_window(
    service: AnalyticsService, analytics_repository: FakeAnalyticsRepository
) -> None:
    page = service.stock_trends(TrendQuery.model_validate({"from": "2026-11-16T19:45:00Z"}))

    assert analytics_repository.trend_filters[0].start == at(16, 19)
    assert page.window.start == at(16, 19, 45)


def test_trends_range_is_measured_to_now_when_to_is_missing(
    analytics_repository: FakeAnalyticsRepository,
) -> None:
    service = AnalyticsService(
        analytics_repository, trends_max_range=timedelta(days=2), clock=lambda: NOW
    )

    with pytest.raises(RejectedError) as caught:
        service.stock_trends(TrendQuery.model_validate({"from": "2026-11-10T00:00:00Z"}))

    assert caught.value.errors[0].field == "from"
    assert "2 days" in caught.value.errors[0].message


def test_from_must_precede_to(service: AnalyticsService) -> None:
    query = AlertQuery.model_validate(
        {"from": "2026-11-16T10:00:00Z", "to": "2026-11-16T10:00:00Z"}
    )

    with pytest.raises(RejectedError):
        service.list_alerts(query)


def test_a_failure_in_the_repository_propagates(
    service: AnalyticsService, analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.error = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        service.list_alerts(AlertQuery())


def test_pages_are_cut_to_the_requested_size(
    service: AnalyticsService, analytics_repository: FakeAnalyticsRepository
) -> None:
    analytics_repository.alerts = [make_alert_record(alert_id=f"a{i}") for i in range(4)]

    page = service.list_alerts(AlertQuery.model_validate({"limit": "3"}))

    assert len(page.items) == 3
    assert page.has_more is True
