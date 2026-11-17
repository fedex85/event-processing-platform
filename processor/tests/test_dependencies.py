import pytest

from common.tests.fakes import FakeGateway
from processor import dependencies
from processor.config import ProcessorSettings
from processor.repositories import BigQueryRepository, GoogleBigQueryGateway, InMemoryRepository


def test_without_a_project_everything_stays_in_memory() -> None:
    repository = dependencies._build_repository(ProcessorSettings(environment="local"))

    assert isinstance(repository, InMemoryRepository)


def test_with_a_project_bigquery_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[str, int | None]] = []

    def fake_from_project(project_id: str, *, maximum_bytes_billed: int | None) -> FakeGateway:
        created.append((project_id, maximum_bytes_billed))
        return FakeGateway()

    monkeypatch.setattr(GoogleBigQueryGateway, "from_project", staticmethod(fake_from_project))

    repository = dependencies._build_repository(
        ProcessorSettings(environment="staging", gcp_project_id="my-project", bq_dataset="ds")
    )

    assert isinstance(repository, BigQueryRepository)
    assert created == [("my-project", 1_000_000_000)]


def test_build_dependencies_uses_the_given_repositories() -> None:
    repo = InMemoryRepository()

    deps = dependencies.build_dependencies(ProcessorSettings(), events=repo, alerts=repo)

    assert deps.processor is not None
