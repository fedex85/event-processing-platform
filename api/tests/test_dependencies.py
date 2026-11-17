import pytest

from api import dependencies
from api.config import ApiSettings
from api.repositories import BigQueryAnalyticsRepository, EmptyAnalyticsRepository
from common.bigquery import GoogleBigQueryGateway
from common.tests.fakes import FakeGateway


def test_without_a_project_the_read_endpoints_return_empty_results() -> None:
    repository = dependencies._build_analytics_repository(
        ApiSettings(environment="local", api_keys="k")
    )

    assert isinstance(repository, EmptyAnalyticsRepository)
    assert repository.find_trends.__name__ == "find_trends"


def test_with_a_project_bigquery_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    def fake_from_project(project_id: str) -> FakeGateway:
        created.append(project_id)
        return FakeGateway()

    monkeypatch.setattr(GoogleBigQueryGateway, "from_project", staticmethod(fake_from_project))
    settings = ApiSettings(
        environment="staging",
        gcp_project_id="my-project",
        api_keys="k",
        pubsub_topic_id="stock-events",
    )

    repository = dependencies._build_analytics_repository(settings)

    assert isinstance(repository, BigQueryAnalyticsRepository)
    assert created == ["my-project"]
