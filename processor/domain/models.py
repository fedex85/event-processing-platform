"""Alert model and the identifiers that make writing it idempotent."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from common.alerts import AlertStatus, AlertType, Severity

__all__ = [
    "Alert",
    "AlertStatus",
    "AlertType",
    "EventLookup",
    "ProcessingStatus",
    "Severity",
    "alert_id_for",
]

# Fixed namespace so the same (event, alert type) always yields the same alert_id.
_ALERT_NAMESPACE: UUID = uuid5(NAMESPACE_URL, "https://inventory-event-platform/alerts")


class ProcessingStatus(StrEnum):
    PROCESSED = "PROCESSED"


def alert_id_for(event_id: str, alert_type: AlertType) -> str:
    """Deterministic id: redelivering an event regenerates the same alerts, not new ones."""
    return str(uuid5(_ALERT_NAMESPACE, f"{event_id}:{alert_type.value}"))


@dataclass(frozen=True)
class Alert:
    alert_id: str
    event_id: str
    store_id: str
    sku: str
    alert_type: AlertType
    severity: Severity
    detected_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
    status: AlertStatus = AlertStatus.OPEN


@dataclass(frozen=True)
class EventLookup:
    """What the processor needs to know about the past before judging an event.

    ``recent_max_quantity`` is the highest stock level reported by a
    ``STOCK_UPDATED`` event for the same store and SKU inside the rule window,
    or ``None`` when there is no history.
    """

    is_duplicate: bool
    recent_max_quantity: int | None = None
