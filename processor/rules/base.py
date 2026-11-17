"""Shared rule inputs and the alert constructor."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from common.events import StockEvent
from processor.domain.models import Alert, AlertType, Severity, alert_id_for


@dataclass(frozen=True)
class RuleConfig:
    """Thresholds. Defaults match the product requirements."""

    low_stock_threshold: int = 5
    rapid_drop_ratio: float = 0.5
    rapid_drop_window_minutes: int = 15
    # A drop from 2 to 0 is 100% but not worth an alert; below this baseline the rule stays quiet.
    rapid_drop_min_baseline: int = 4

    @property
    def rapid_drop_window(self) -> timedelta:
        return timedelta(minutes=self.rapid_drop_window_minutes)


@dataclass(frozen=True)
class RuleContext:
    config: RuleConfig
    detected_at: datetime
    recent_max_quantity: int | None = None


def build_alert(
    event: StockEvent,
    context: RuleContext,
    *,
    alert_type: AlertType,
    severity: Severity,
    details: dict[str, Any],
) -> Alert:
    return Alert(
        alert_id=alert_id_for(event.event_id, alert_type),
        event_id=event.event_id,
        store_id=event.store_id,
        sku=event.sku,
        alert_type=alert_type,
        severity=severity,
        detected_at=context.detected_at,
        details=details,
    )
