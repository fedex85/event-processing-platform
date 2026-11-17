"""Factories for test data."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from api.repositories.base import AlertRecord, TrendRecord


def make_event_payload(*, omit: Iterable[str] = (), **overrides: Any) -> dict[str, Any]:
    """Build a valid event payload, then apply overrides and drop ``omit`` keys."""
    payload: dict[str, Any] = {
        "event_id": "evt_01J5Z8K9Q2M7",
        "store_id": "store_014",
        "sku": "SKU-88231",
        "event_type": "STOCK_UPDATED",
        "quantity": 3,
        "previous_quantity": 18,
        "unit": "units",
        "occurred_at": "2026-11-16T19:40:12Z",
        "source": "pos-system",
        "metadata": {"region": "asturias", "channel": "physical_store"},
    }
    payload.update(overrides)
    for key in omit:
        payload.pop(key, None)
    return payload


NOW = datetime(2026, 11, 17, 12, 30, tzinfo=UTC)


def make_alert_record(**overrides: Any) -> AlertRecord:
    values: dict[str, Any] = {
        "alert_id": "alert-1",
        "event_id": "evt_01J5Z8K9Q2M7",
        "store_id": "store_014",
        "sku": "SKU-88231",
        "alert_type": "LOW_STOCK",
        "severity": "MEDIUM",
        "detected_at": datetime(2026, 11, 16, 19, 40, 13, tzinfo=UTC),
        "status": "OPEN",
        "details": {"quantity": 3, "threshold": 5, "unit": "units"},
    }
    values.update(overrides)
    return AlertRecord(**values)


def make_trend_record(**overrides: Any) -> TrendRecord:
    values: dict[str, Any] = {
        "hour_start": datetime(2026, 11, 16, 19, 0, tzinfo=UTC),
        "store_id": "store_014",
        "sku": "SKU-88231",
        "units_sold": 12,
        "units_restocked": 40,
        "avg_stock": 22.456,
        "event_count": 9,
        "stock_variation": 28,
    }
    values.update(overrides)
    return TrendRecord(**values)
