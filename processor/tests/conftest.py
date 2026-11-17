import pytest
from flask import Flask
from flask.testing import FlaskClient

from common.structured_logging import clear_context
from processor.app import create_app
from processor.config import ProcessorSettings
from processor.dependencies import build_dependencies
from processor.tests.fakes import ScriptedRepository


@pytest.fixture(autouse=True)
def _reset_log_context() -> None:
    clear_context()


@pytest.fixture
def repository() -> ScriptedRepository:
    return ScriptedRepository()


@pytest.fixture
def settings() -> ProcessorSettings:
    return ProcessorSettings(environment="local")


@pytest.fixture
def app(settings: ProcessorSettings, repository: ScriptedRepository) -> Flask:
    dependencies = build_dependencies(settings, events=repository, alerts=repository)
    return create_app(settings, dependencies=dependencies)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
