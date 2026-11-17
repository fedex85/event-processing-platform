"""Settings for ``inventory-processor``."""

from pydantic import Field

from common.settings import BigQuerySettings
from processor.rules.base import RuleConfig


class ProcessorSettings(BigQuerySettings):
    service_name: str = "inventory-processor"

    # BigQuery. With GCP_PROJECT_ID set the processor writes to BigQuery; without it
    # (local development only) it keeps everything in memory.
    bq_events_table: str = "stock_events"
    bq_alerts_table: str = "stock_alerts"
    # The timeout and retry defaults come from BigQuerySettings. Each call may take
    # timeout x attempts, and three operations per message must fit in the gunicorn timeout
    # (60 s) and the push subscription's ack deadline.

    # Business rules.
    low_stock_threshold: int = Field(default=5, ge=0)
    rapid_drop_ratio: float = Field(default=0.5, gt=0, lt=1)
    rapid_drop_window_minutes: int = Field(default=15, ge=1, le=1440)
    rapid_drop_min_baseline: int = Field(default=4, ge=1)

    @property
    def rule_config(self) -> RuleConfig:
        return RuleConfig(
            low_stock_threshold=self.low_stock_threshold,
            rapid_drop_ratio=self.rapid_drop_ratio,
            rapid_drop_window_minutes=self.rapid_drop_window_minutes,
            rapid_drop_min_baseline=self.rapid_drop_min_baseline,
        )
