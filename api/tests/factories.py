"""Factories for test data."""

from collections.abc import Iterable
from typing import Any


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
