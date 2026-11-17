import pytest
from pydantic import ValidationError

from processor.config import ProcessorSettings


def test_defaults_are_suitable_for_local_development() -> None:
    settings = ProcessorSettings()

    assert settings.environment == "local"
    assert settings.service_name == "inventory-processor"
    assert settings.port == 8080


def test_project_id_is_required_outside_local() -> None:
    with pytest.raises(ValidationError, match="GCP_PROJECT_ID is required"):
        ProcessorSettings(environment="prod")


def test_project_id_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")

    assert ProcessorSettings().gcp_project_id == "my-project"


def test_business_rule_defaults_match_the_product_requirements() -> None:
    config = ProcessorSettings().rule_config

    assert config.low_stock_threshold == 5
    assert config.rapid_drop_ratio == 0.5
    assert config.rapid_drop_window_minutes == 15


def test_bigquery_defaults() -> None:
    settings = ProcessorSettings()

    assert (settings.bq_dataset, settings.bq_events_table, settings.bq_alerts_table) == (
        "inventory_analytics",
        "stock_events",
        "stock_alerts",
    )
    policy = settings.retry_policy
    assert (policy.attempts, policy.base_delay_seconds, policy.max_delay_seconds) == (3, 0.2, 2.0)


def test_rules_and_retries_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOW_STOCK_THRESHOLD", "8")
    monkeypatch.setenv("RAPID_DROP_RATIO", "0.4")
    monkeypatch.setenv("RAPID_DROP_WINDOW_MINUTES", "30")
    monkeypatch.setenv("RAPID_DROP_MIN_BASELINE", "6")
    monkeypatch.setenv("BQ_RETRY_ATTEMPTS", "5")
    monkeypatch.setenv("BQ_DATASET", "other_dataset")

    settings = ProcessorSettings()

    config = settings.rule_config
    assert (config.low_stock_threshold, config.rapid_drop_ratio) == (8, 0.4)
    assert (config.rapid_drop_window_minutes, config.rapid_drop_min_baseline) == (30, 6)
    assert settings.retry_policy.attempts == 5
    assert settings.bq_dataset == "other_dataset"


@pytest.mark.parametrize(
    "overrides",
    [
        {"rapid_drop_ratio": 0},
        {"rapid_drop_ratio": 1},
        {"rapid_drop_window_minutes": 0},
        {"bq_retry_attempts": 0},
        {"bq_timeout_seconds": 0},
        {"low_stock_threshold": -1},
        {"bq_retry_base_delay_seconds": 3.0, "bq_retry_max_delay_seconds": 1.0},
    ],
)
def test_invalid_values_are_rejected(overrides: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        ProcessorSettings.model_validate(overrides)
