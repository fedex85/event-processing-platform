"""Port for reading analytics data, and the plain records that cross it."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from common.alerts import AlertStatus, AlertType, Severity


@dataclass(frozen=True)
class AlertFilter:
    start: datetime  # inclusive
    limit: int
    offset: int
    end: datetime | None = None  # exclusive
    store_id: str | None = None
    sku: str | None = None
    alert_type: AlertType | None = None
    severity: Severity | None = None
    status: AlertStatus | None = None


@dataclass(frozen=True)
class AlertRecord:
    alert_id: str
    event_id: str
    store_id: str
    sku: str
    alert_type: str
    severity: str
    detected_at: datetime
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrendFilter:
    start: datetime  # inclusive, a whole hour
    limit: int
    offset: int
    end: datetime | None = None  # exclusive
    store_id: str | None = None
    sku: str | None = None


@dataclass(frozen=True)
class TrendRecord:
    hour_start: datetime
    store_id: str
    sku: str
    units_sold: int
    units_restocked: int
    avg_stock: float | None
    event_count: int
    stock_variation: int | None


class AnalyticsRepository(Protocol):
    def find_alerts(self, criteria: AlertFilter) -> list[AlertRecord]:
        """Alerts matching the filter, newest first, at most ``criteria.limit`` of them."""
        ...

    def find_trends(self, criteria: TrendFilter) -> list[TrendRecord]:
        """Hourly aggregates, newest hour first, at most ``criteria.limit`` of them."""
        ...
