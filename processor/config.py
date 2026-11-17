"""Settings for ``inventory-processor``."""

from typing import Self

from pydantic import Field, model_validator

from common.settings import BaseServiceSettings
from processor.repositories.retry import RetryPolicy
from processor.rules.base import RuleConfig


class ProcessorSettings(BaseServiceSettings):
    service_name: str = "inventory-processor"

    # BigQuery. With GCP_PROJECT_ID set the processor writes to BigQuery; without it
    # (local development only) it keeps everything in memory.
    bq_dataset: str = "inventory_analytics"
    bq_events_table: str = "stock_events"
    bq_alerts_table: str = "stock_alerts"
    # Each call may take timeout x attempts. Three operations per message must fit in the
    # gunicorn timeout (60 s) and the push subscription's ack deadline.
    bq_timeout_seconds: float = Field(default=5.0, gt=0)
    bq_retry_attempts: int = Field(default=3, ge=1, le=10)
    bq_retry_base_delay_seconds: float = Field(default=0.2, ge=0)
    bq_retry_max_delay_seconds: float = Field(default=2.0, ge=0)

    # Business rules.
    low_stock_threshold: int = Field(default=5, ge=0)
    rapid_drop_ratio: float = Field(default=0.5, gt=0, lt=1)
    rapid_drop_window_minutes: int = Field(default=15, ge=1, le=1440)
    rapid_drop_min_baseline: int = Field(default=4, ge=1)

    @model_validator(mode="after")
    def _retry_delays_are_ordered(self) -> Self:
        if self.bq_retry_max_delay_seconds < self.bq_retry_base_delay_seconds:
            raise ValueError("BQ_RETRY_MAX_DELAY_SECONDS must be >= BQ_RETRY_BASE_DELAY_SECONDS")
        return self

    @property
    def rule_config(self) -> RuleConfig:
        return RuleConfig(
            low_stock_threshold=self.low_stock_threshold,
            rapid_drop_ratio=self.rapid_drop_ratio,
            rapid_drop_window_minutes=self.rapid_drop_window_minutes,
            rapid_drop_min_baseline=self.rapid_drop_min_baseline,
        )

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            attempts=self.bq_retry_attempts,
            base_delay_seconds=self.bq_retry_base_delay_seconds,
            max_delay_seconds=self.bq_retry_max_delay_seconds,
        )
