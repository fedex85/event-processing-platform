"""In-memory adapter for local development and tests. Nothing survives a restart."""

import threading
from collections.abc import Sequence
from datetime import timedelta

from common.events import EventType, IngestedStockEvent
from processor.domain.models import Alert, EventLookup


class InMemoryRepository:
    """Implements both repository ports. Unbounded: only for local runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, IngestedStockEvent] = {}
        self._alerts: dict[str, Alert] = {}

    @property
    def events(self) -> list[IngestedStockEvent]:
        with self._lock:
            return list(self._events.values())

    @property
    def alerts(self) -> list[Alert]:
        with self._lock:
            return list(self._alerts.values())

    def lookup(self, event: IngestedStockEvent, window: timedelta) -> EventLookup:
        window_start = event.occurred_at - window
        with self._lock:
            is_duplicate = event.event_id in self._events
            recent = [
                stored.quantity
                for stored in self._events.values()
                if stored.store_id == event.store_id
                and stored.sku == event.sku
                and stored.event_type is EventType.STOCK_UPDATED
                and window_start <= stored.occurred_at <= event.occurred_at
            ]
        return EventLookup(is_duplicate=is_duplicate, recent_max_quantity=max(recent, default=None))

    def save_event(self, event: IngestedStockEvent) -> None:
        with self._lock:
            self._events.setdefault(event.event_id, event)

    def save_alerts(self, alerts: Sequence[Alert]) -> None:
        with self._lock:
            for alert in alerts:
                self._alerts.setdefault(alert.alert_id, alert)
