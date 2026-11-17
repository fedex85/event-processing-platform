"""Factories for processor test data."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from common.events import IngestedStockEvent
from processor.rules.base import RuleConfig, RuleContext

OCCURRED_AT = datetime(2026, 11, 16, 19, 40, 12, tzinfo=UTC)
DETECTED_AT = datetime(2026, 11, 16, 19, 40, 13, tzinfo=UTC)


def make_event_payload(**overrides: Any) -> dict[str, Any]:
    """The JSON ``inventory-api`` publishes: an event plus ``ingested_at``."""
    payload: dict[str, Any] = {
        "event_id": "evt_01J5Z8K9Q2M7",
        "store_id": "store_014",
        "sku": "SKU-88231",
        "event_type": "STOCK_UPDATED",
        "quantity": 30,
        "previous_quantity": 31,
        "unit": "units",
        "occurred_at": OCCURRED_AT.isoformat().replace("+00:00", "Z"),
        "source": "pos-system",
        "metadata": {"region": "asturias", "channel": "physical_store"},
        "ingested_at": (OCCURRED_AT + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    }
    payload.update(overrides)
    return payload


def make_event(**overrides: Any) -> IngestedStockEvent:
    return IngestedStockEvent.model_validate(make_event_payload(**overrides))


def make_context(
    *,
    recent_max_quantity: int | None = None,
    config: RuleConfig | None = None,
) -> RuleContext:
    return RuleContext(
        config=config or RuleConfig(),
        detected_at=DETECTED_AT,
        recent_max_quantity=recent_max_quantity,
    )


def encode_data(payload: Any) -> str:
    """Base64 of the JSON message body, as Pub/Sub delivers it."""
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return base64.b64encode(raw).decode()


def make_envelope(
    payload: Any = None,
    *,
    data: str | None = None,
    attributes: dict[str, str] | None = None,
    delivery_attempt: int | None = None,
) -> dict[str, Any]:
    """A Pub/Sub push request body."""
    message: dict[str, Any] = {
        "data": data if data is not None else encode_data(payload or make_event_payload()),
        "messageId": "1234567890",
        "publishTime": "2026-11-16T19:40:13.100Z",
        "attributes": attributes if attributes is not None else {"schema_version": "1"},
    }
    envelope: dict[str, Any] = {
        "message": message,
        "subscription": "projects/p/subscriptions/stock-events-processor",
    }
    if delivery_attempt is not None:
        envelope["deliveryAttempt"] = delivery_attempt
    return envelope
