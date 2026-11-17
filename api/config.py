"""Settings for ``inventory-api``."""

from typing import Any, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from common.settings import BigQuerySettings

# Generate keys with e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
MIN_API_KEY_LENGTH = 24


class ApiSettings(BigQuerySettings):
    service_name: str = "inventory-api"

    # Authentication. Comma-separated list; deployed environments read it from Secret Manager.
    api_keys: SecretStr = SecretStr("")

    # Ingestion.
    max_batch_size: int = Field(default=100, ge=1, le=100)
    pubsub_topic_id: str | None = None
    pubsub_publish_timeout_seconds: float = Field(default=10.0, gt=0)

    # Protection. Both are per Cloud Run instance, not global.
    rate_limit_per_minute: int = Field(default=600, ge=1)
    idempotency_ttl_seconds: int = Field(default=900, ge=1)
    idempotency_max_entries: int = Field(default=100_000, ge=1)

    # Accepted range for occurred_at. The caps keep events inside what BigQuery can stream
    # into a partitioned table (31 days back, 16 days ahead), with a day of margin.
    max_event_age_days: int = Field(default=30, ge=1, le=30)
    max_event_future_days: int = Field(default=15, ge=0, le=15)

    # Reads. With GCP_PROJECT_ID set the read endpoints query BigQuery; without it (local
    # development only) they return empty lists.
    bq_alerts_table: str = "stock_alerts"
    bq_trends_view: str = "v_stock_trends"
    bq_timeout_seconds: float = Field(default=8.0, gt=0)
    bq_retry_attempts: int = Field(default=2, ge=1, le=5)
    bq_retry_base_delay_seconds: float = Field(default=0.1, ge=0)
    bq_retry_max_delay_seconds: float = Field(default=0.5, ge=0)
    alerts_default_lookback_days: int = Field(default=7, ge=1, le=365)
    trends_default_lookback_hours: int = Field(default=24, ge=1, le=720)
    trends_max_range_days: int = Field(default=31, ge=1, le=366)

    @field_validator("pubsub_topic_id", mode="before")
    @classmethod
    def _blank_topic_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def api_key_set(self) -> frozenset[str]:
        raw = self.api_keys.get_secret_value()
        return frozenset(key.strip() for key in raw.split(",") if key.strip())

    @model_validator(mode="after")
    def _require_api_keys_outside_local(self) -> Self:
        if self.environment != "local" and not self.api_key_set:
            raise ValueError("API_KEYS is required when ENVIRONMENT is not 'local'")
        return self

    @model_validator(mode="after")
    def _require_strong_api_keys_outside_local(self) -> Self:
        if self.environment != "local" and any(
            len(key) < MIN_API_KEY_LENGTH for key in self.api_key_set
        ):
            raise ValueError(f"every API key must have at least {MIN_API_KEY_LENGTH} characters")
        return self

    @model_validator(mode="after")
    def _require_topic_outside_local(self) -> Self:
        if self.environment != "local" and not self.pubsub_topic_id:
            raise ValueError("PUBSUB_TOPIC_ID is required when ENVIRONMENT is not 'local'")
        return self
