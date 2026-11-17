"""Settings every service shares. Values come from environment variables."""

from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = "local"
    service_name: str = "inventory-service"
    log_level: LogLevel = "INFO"
    port: int = Field(default=8080, ge=1, le=65535)
    gcp_project_id: str | None = None

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
