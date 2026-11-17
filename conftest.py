"""Test isolation shared by every test suite.

Settings read the process environment and a ``.env`` file in the working
directory. Tests must not depend on either, so each test starts with a clean
environment in an empty directory.
"""

from pathlib import Path

import pytest

SETTINGS_ENV_VARS = (
    "ENVIRONMENT",
    "SERVICE_NAME",
    "LOG_LEVEL",
    "PORT",
    "GCP_PROJECT_ID",
    "API_KEYS",
    "MAX_BATCH_SIZE",
    "PUBSUB_TOPIC_ID",
    "PUBSUB_PUBLISH_TIMEOUT_SECONDS",
    "RATE_LIMIT_PER_MINUTE",
    "IDEMPOTENCY_TTL_SECONDS",
    "IDEMPOTENCY_MAX_ENTRIES",
    "SIMULATOR_API_KEY",
    "BQ_DATASET",
    "BQ_EVENTS_TABLE",
    "BQ_ALERTS_TABLE",
    "BQ_TRENDS_VIEW",
    "BQ_TIMEOUT_SECONDS",
    "BQ_RETRY_ATTEMPTS",
    "BQ_RETRY_BASE_DELAY_SECONDS",
    "BQ_RETRY_MAX_DELAY_SECONDS",
    "LOW_STOCK_THRESHOLD",
    "RAPID_DROP_RATIO",
    "RAPID_DROP_WINDOW_MINUTES",
    "RAPID_DROP_MIN_BASELINE",
    "ALERTS_DEFAULT_LOOKBACK_DAYS",
    "TRENDS_DEFAULT_LOOKBACK_HOURS",
    "TRENDS_MAX_RANGE_DAYS",
)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
