from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from api.tests.factories import make_event_payload
from common.events import IngestedStockEvent, StockEvent, format_timestamp, to_error_items


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


# --- metadata limits ---


def _event(**overrides: object) -> dict[str, object]:
    return {
        "store_id": "s",
        "sku": "k",
        "event_type": "SALE",
        "quantity": 1,
        "occurred_at": "2026-11-16T19:40:12Z",
        "source": "pos",
        **overrides,
    }


def test_metadata_over_the_size_limit_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        StockEvent.model_validate(_event(metadata={"blob": "x" * 5000}))

    [item] = to_error_items(caught.value)
    assert item.field == "metadata"
    assert "4096 bytes" in item.message


def test_metadata_at_the_limit_is_accepted() -> None:
    padding = "x" * (4096 - len('{"b":""}'))

    assert StockEvent.model_validate(_event(metadata={"b": padding})).metadata["b"] == padding


def test_metadata_may_not_hold_non_finite_numbers() -> None:
    with pytest.raises(ValidationError):
        StockEvent.model_validate(_event(metadata={"ratio": float("nan")}))


def test_metadata_size_counts_bytes_not_characters() -> None:
    with pytest.raises(ValidationError):
        StockEvent.model_validate(_event(metadata={"b": "ñ" * 2500}))


def test_timestamps_are_formatted_as_utc_with_z() -> None:
    assert (
        format_timestamp(datetime(2026, 11, 16, 19, 40, 13, tzinfo=UTC)) == "2026-11-16T19:40:13Z"
    )
