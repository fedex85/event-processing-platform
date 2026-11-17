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
)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
