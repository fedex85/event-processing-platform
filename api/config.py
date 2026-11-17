"""Settings for ``inventory-api``."""

from typing import Any, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from common.settings import BaseServiceSettings


class ApiSettings(BaseServiceSettings):
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
    def _require_topic_outside_local(self) -> Self:
        if self.environment != "local" and not self.pubsub_topic_id:
            raise ValueError("PUBSUB_TOPIC_ID is required when ENVIRONMENT is not 'local'")
        return self
