from typing import Any

import pytest
from pydantic import ValidationError

from api.config import ApiSettings


def load(**overrides: Any) -> ApiSettings:
    return ApiSettings(**overrides)


def test_defaults_are_suitable_for_local_development() -> None:
    settings = load()

    assert settings.environment == "local"
    assert settings.service_name == "inventory-api"
    assert settings.log_level == "INFO"
    assert settings.port == 8080
    assert settings.gcp_project_id is None
    assert settings.max_batch_size == 100
    assert settings.api_key_set == frozenset()
    assert settings.pubsub_topic_id is None
    assert settings.pubsub_publish_timeout_seconds == 10
    assert settings.rate_limit_per_minute == 600
    assert settings.idempotency_ttl_seconds == 900
    assert settings.idempotency_max_entries == 100_000


def test_values_come_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("PUBSUB_TOPIC_ID", "stock-events")
    monkeypatch.setenv("PORT", "9000")

    settings = load()

    assert settings.environment == "staging"
    assert settings.gcp_project_id == "my-project"
    assert settings.port == 9000


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert load().log_level == "DEBUG"


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load(log_level="LOUD")


def test_blank_project_id_counts_as_unset() -> None:
    assert load(gcp_project_id="  ").gcp_project_id is None


def test_project_id_is_required_outside_local() -> None:
    with pytest.raises(ValidationError, match="GCP_PROJECT_ID is required"):
        load(environment="prod", api_keys="k1")


def test_api_keys_are_required_outside_local() -> None:
    with pytest.raises(ValidationError, match="API_KEYS is required"):
        load(environment="prod", gcp_project_id="my-project", pubsub_topic_id="stock-events")


def test_topic_is_required_outside_local() -> None:
    with pytest.raises(ValidationError, match="PUBSUB_TOPIC_ID is required"):
        load(environment="prod", gcp_project_id="my-project", api_keys="k1")


def test_a_fully_configured_production_setup_is_valid() -> None:
    settings = load(
        environment="prod",
        gcp_project_id="my-project",
        api_keys="k1",
        pubsub_topic_id="stock-events",
    )

    assert settings.pubsub_topic_id == "stock-events"


def test_blank_topic_counts_as_unset() -> None:
    assert load(pubsub_topic_id="  ").pubsub_topic_id is None


def test_api_keys_are_parsed_from_a_comma_separated_list() -> None:
    settings = load(api_keys=" k1, k2 ,,k3 ")

    assert settings.api_key_set == frozenset({"k1", "k2", "k3"})


def test_api_keys_are_not_exposed_in_repr() -> None:
    settings = load(api_keys="super-secret-key")

    assert "super-secret-key" not in repr(settings)
    assert "super-secret-key" not in str(settings)


@pytest.mark.parametrize("value", [0, 101, -1])
def test_batch_size_is_limited_to_100(value: int) -> None:
    with pytest.raises(ValidationError):
        load(max_batch_size=value)


@pytest.mark.parametrize("name", ["rate_limit_per_minute", "idempotency_ttl_seconds"])
def test_protection_settings_must_be_positive(name: str) -> None:
    with pytest.raises(ValidationError):
        load(**{name: 0})


def test_publish_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        load(pubsub_publish_timeout_seconds=0)


@pytest.mark.parametrize("value", [0, 70000])
def test_port_must_be_valid(value: int) -> None:
    with pytest.raises(ValidationError):
        load(port=value)
