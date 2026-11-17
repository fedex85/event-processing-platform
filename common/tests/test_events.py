from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from api.tests.factories import make_event_payload
from common.events import IngestedStockEvent, StockEvent


def ingested_payload(**overrides: object) -> dict[str, object]:
    return {**make_event_payload(), "ingested_at": "2026-11-17T08:30:00Z", **overrides}


def test_ingested_event_extends_the_event_with_its_ingestion_time() -> None:
    event = IngestedStockEvent.model_validate(ingested_payload())

    assert event.ingested_at == datetime(2026, 11, 17, 8, 30, tzinfo=UTC)
    assert event.store_id == "store_014"


def test_ingested_at_is_required() -> None:
    with pytest.raises(ValidationError):
        IngestedStockEvent.model_validate(make_event_payload())


def test_ingested_at_must_include_a_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        IngestedStockEvent.model_validate(ingested_payload(ingested_at="2026-11-17T08:30:00"))


def test_a_plain_event_does_not_accept_ingested_at() -> None:
    with pytest.raises(ValidationError):
        StockEvent.model_validate(ingested_payload())


def test_the_pubsub_message_round_trips_through_json() -> None:
    original = IngestedStockEvent.model_validate(ingested_payload())

    decoded = IngestedStockEvent.model_validate_json(original.model_dump_json())

    assert decoded == original
