"""Ports the processing service depends on. Adapters live next to this file."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from common.events import IngestedStockEvent
from processor.domain.models import Alert, EventLookup


class EventRepository(Protocol):
    def lookup(self, event: IngestedStockEvent, window: timedelta) -> EventLookup:
        """Say whether ``event.event_id`` is already stored and what the recent stock looked like.

        Duplicates are searched among events of the same store and SKU with the
        same ``occurred_at`` (a resent event always carries the same one).
        """
        ...

    def save_event(self, event: IngestedStockEvent) -> None:
        """Store the event. Must be safe to call twice for the same ``event_id``."""
        ...


class AlertRepository(Protocol):
    def save_alerts(self, alerts: Sequence[Alert]) -> None:
        """Store alerts. Must be safe to call twice with the same ``alert_id``."""
        ...
