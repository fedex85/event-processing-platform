import pytest
from flask import Flask
from flask.testing import FlaskClient

from api.app import create_app
from api.config import ApiSettings
from api.dependencies import build_dependencies
from api.tests.fakes import FakePublisher
from common.structured_logging import clear_context

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _reset_log_context() -> None:
    clear_context()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(environment="local", api_keys=API_KEY)


@pytest.fixture
def app(settings: ApiSettings, publisher: FakePublisher) -> Flask:
    dependencies = build_dependencies(settings, publisher=publisher)
    return create_app(settings, dependencies=dependencies)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def auth() -> dict[str, str]:
    """Headers that authenticate a request."""
    return {"X-API-Key": API_KEY}
