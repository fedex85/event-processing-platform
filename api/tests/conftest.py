from dataclasses import replace

import pytest
from flask import Flask
from flask.testing import FlaskClient

from api.app import create_app
from api.config import ApiSettings
from api.dependencies import build_dependencies
from api.services import event_window
from api.services.analytics import AnalyticsService
from api.tests.factories import NOW
from api.tests.fakes import FakeAnalyticsRepository, FakePublisher
from common.structured_logging import clear_context

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _reset_log_context() -> None:
    clear_context()


@pytest.fixture(autouse=True)
def _fixed_clock_for_event_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Payloads in the tests carry fixed dates, so the accepted window must not drift."""
    monkeypatch.setattr(event_window, "_utcnow", lambda: NOW)


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def analytics_repository() -> FakeAnalyticsRepository:
    return FakeAnalyticsRepository()


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(environment="local", api_keys=API_KEY)


@pytest.fixture
def app(
    settings: ApiSettings,
    publisher: FakePublisher,
    analytics_repository: FakeAnalyticsRepository,
) -> Flask:
    dependencies = build_dependencies(
        settings, publisher=publisher, analytics_repository=analytics_repository
    )
    # A fixed clock makes the default time windows predictable.
    dependencies = replace(
        dependencies, analytics=AnalyticsService(analytics_repository, clock=lambda: NOW)
    )
    return create_app(settings, dependencies=dependencies)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def auth() -> dict[str, str]:
    """Headers that authenticate a request."""
    return {"X-API-Key": API_KEY}
