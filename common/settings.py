"""Settings every service shares. Values come from environment variables."""

from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.retry import RetryPolicy

Environment = Literal["local", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = "local"
    service_name: str = "inventory-service"
    log_level: LogLevel = "INFO"
    port: int = Field(default=8080, ge=1, le=65535)
    gcp_project_id: str | None = None
    # Requests larger than this are refused with 413 before the body is read in full.
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    # BigQuery refuses queries that would scan more than this (the minimum billed is 10 MB).
    bq_max_bytes_billed: int = Field(default=1_000_000_000, ge=10_000_000)

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("gcp_project_id", mode="before")
    @classmethod
    def _blank_project_is_unset(cls, value: Any) -> Any:
        # ``GCP_PROJECT_ID=`` in a .env file arrives as an empty string.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _require_project_outside_local(self) -> Self:
        if self.environment != "local" and not self.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required when ENVIRONMENT is not 'local'")
        return self


class BigQuerySettings(BaseServiceSettings):
    """Settings of a service that talks to BigQuery: names, timeout and retry policy.

    Each service redeclares the numeric fields with defaults that suit it; the rules that
    relate them live here once.
    """

    bq_dataset: str = "inventory_analytics"
    bq_timeout_seconds: float = Field(default=5.0, gt=0)
    bq_retry_attempts: int = Field(default=3, ge=1, le=10)
    bq_retry_base_delay_seconds: float = Field(default=0.2, ge=0)
    bq_retry_max_delay_seconds: float = Field(default=2.0, ge=0)

    @model_validator(mode="after")
    def _retry_delays_are_ordered(self) -> Self:
        if self.bq_retry_max_delay_seconds < self.bq_retry_base_delay_seconds:
            raise ValueError("BQ_RETRY_MAX_DELAY_SECONDS must be >= BQ_RETRY_BASE_DELAY_SECONDS")
        return self

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            attempts=self.bq_retry_attempts,
            base_delay_seconds=self.bq_retry_base_delay_seconds,
            max_delay_seconds=self.bq_retry_max_delay_seconds,
        )
