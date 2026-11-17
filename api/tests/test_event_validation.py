import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from api.schemas import parse_event
from api.tests.factories import make_event_payload
from common.errors import RejectedError
from common.events import EventType

INTEGER_MESSAGE = "must be an integer greater than or equal to 0"


def rejected(payload: Any) -> list[dict[str, str]]:
    with pytest.raises(RejectedError) as info:
        parse_event(payload)
    return [item.model_dump() for item in info.value.errors]


class TestValidEvents:
    def test_full_event_is_parsed(self) -> None:
        event = parse_event(make_event_payload())

        assert event.event_id == "evt_01J5Z8K9Q2M7"
        assert event.store_id == "store_014"
        assert event.event_type is EventType.STOCK_UPDATED
        assert event.quantity == 3
        assert event.previous_quantity == 18
        assert event.occurred_at == datetime(2026, 11, 16, 19, 40, 12, tzinfo=UTC)
        assert event.metadata == {"region": "asturias", "channel": "physical_store"}

    def test_minimal_event_gets_defaults(self) -> None:
        payload = make_event_payload(omit=("event_id", "previous_quantity", "unit", "metadata"))

        event = parse_event(payload)

        uuid.UUID(event.event_id)  # raises if it is not a UUID
        assert event.previous_quantity is None
        assert event.unit == "units"
        assert event.metadata == {}

    def test_null_event_id_is_generated(self) -> None:
        event = parse_event(make_event_payload(event_id=None))

        uuid.UUID(event.event_id)

    def test_generated_event_ids_are_unique(self) -> None:
        payload = make_event_payload(omit=("event_id",))

        assert parse_event(payload).event_id != parse_event(payload).event_id

    @pytest.mark.parametrize("event_type", ["STOCK_UPDATED", "SALE", "RESTOCK"])
    def test_allowed_event_types(self, event_type: str) -> None:
        assert parse_event(make_event_payload(event_type=event_type)).event_type == event_type

    def test_zero_quantity_is_valid(self) -> None:
        assert parse_event(make_event_payload(quantity=0, previous_quantity=0)).quantity == 0

    def test_strings_are_stripped(self) -> None:
        event = parse_event(make_event_payload(store_id="  store_014 ", sku=" SKU-1\n"))

        assert (event.store_id, event.sku) == ("store_014", "SKU-1")

    def test_nested_metadata_is_accepted(self) -> None:
        metadata = {"tags": ["a", "b"], "geo": {"lat": 43.36, "lon": -5.85}}

        assert parse_event(make_event_payload(metadata=metadata)).metadata == metadata


class TestTimestamps:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-11-16T19:40:12Z",
            "2026-11-16T20:40:12+01:00",
            "2026-11-16T19:40:12.123456Z",
        ],
    )
    def test_iso_8601_with_timezone_is_normalized_to_utc(self, value: str) -> None:
        event = parse_event(make_event_payload(occurred_at=value))

        assert event.occurred_at.utcoffset() == UTC.utcoffset(None)
        assert event.occurred_at.date().isoformat() == "2026-11-16"
        assert event.occurred_at.hour == 19

    def test_timestamp_without_timezone_is_rejected(self) -> None:
        errors = rejected(make_event_payload(occurred_at="2026-11-16T19:40:12"))

        assert len(errors) == 1
        assert errors[0]["field"] == "occurred_at"
        assert "timezone" in errors[0]["message"]

    @pytest.mark.parametrize(
        "value",
        ["yesterday", "2026-11-16", "1700000000", 1700000000, "2026-13-45T10:00:00Z", None, ""],
    )
    def test_invalid_timestamps_are_rejected(self, value: Any) -> None:
        errors = rejected(make_event_payload(occurred_at=value))

        assert [error["field"] for error in errors] == ["occurred_at"]

    def test_missing_timestamp_is_rejected(self) -> None:
        errors = rejected(make_event_payload(omit=("occurred_at",)))

        assert errors == [{"field": "occurred_at", "message": "field is required"}]


class TestQuantities:
    @pytest.mark.parametrize("value", [-1, 3.5, 3.0, "3", None, True, []])
    def test_invalid_quantity_is_rejected(self, value: Any) -> None:
        errors = rejected(make_event_payload(quantity=value))

        assert errors == [{"field": "quantity", "message": INTEGER_MESSAGE}]

    def test_missing_quantity_is_rejected(self) -> None:
        errors = rejected(make_event_payload(omit=("quantity",)))

        assert errors == [{"field": "quantity", "message": "field is required"}]

    @pytest.mark.parametrize("value", [-1, 1.5, "7"])
    def test_invalid_previous_quantity_is_rejected(self, value: Any) -> None:
        errors = rejected(make_event_payload(previous_quantity=value))

        assert errors == [{"field": "previous_quantity", "message": INTEGER_MESSAGE}]


class TestRequiredStrings:
    @pytest.mark.parametrize("field", ["store_id", "sku", "source"])
    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_values_are_rejected(self, field: str, value: str) -> None:
        payload = make_event_payload()
        payload[field] = value

        errors = rejected(payload)

        assert errors == [{"field": field, "message": "must not be empty"}]

    @pytest.mark.parametrize("field", ["store_id", "sku", "source", "event_type"])
    def test_missing_fields_are_rejected(self, field: str) -> None:
        errors = rejected(make_event_payload(omit=(field,)))

        assert errors == [{"field": field, "message": "field is required"}]

    @pytest.mark.parametrize("field", ["store_id", "sku", "source"])
    def test_non_string_values_are_rejected(self, field: str) -> None:
        payload = make_event_payload()
        payload[field] = 42

        errors = rejected(payload)

        assert errors == [{"field": field, "message": "must be a string"}]


class TestLengthLimits:
    @pytest.mark.parametrize("field", ["event_id", "store_id", "sku", "source", "unit"])
    def test_values_longer_than_255_characters_are_rejected(self, field: str) -> None:
        payload = make_event_payload()
        payload[field] = "x" * 256

        assert rejected(payload) == [{"field": field, "message": "must be at most 255 characters"}]

    def test_255_characters_are_allowed(self) -> None:
        assert parse_event(make_event_payload(sku="x" * 255)).sku == "x" * 255


class TestEventType:
    @pytest.mark.parametrize("value", ["REFUND", "sale", "", None, 1])
    def test_unknown_event_type_is_rejected(self, value: Any) -> None:
        errors = rejected(make_event_payload(event_type=value))

        assert [error["field"] for error in errors] == ["event_type"]

    def test_message_lists_allowed_values(self) -> None:
        errors = rejected(make_event_payload(event_type="REFUND"))

        assert errors[0]["message"] == "must be one of: STOCK_UPDATED, SALE, RESTOCK"


class TestMetadataAndShape:
    @pytest.mark.parametrize("value", [[], "text", 5, None])
    def test_metadata_must_be_an_object(self, value: Any) -> None:
        errors = rejected(make_event_payload(metadata=value))

        assert errors == [{"field": "metadata", "message": "must be a JSON object"}]

    def test_unknown_fields_are_rejected(self) -> None:
        errors = rejected(make_event_payload(color="red"))

        assert errors == [{"field": "color", "message": "unknown field"}]

    @pytest.mark.parametrize("body", [[], "event", 42, None])
    def test_body_must_be_a_json_object(self, body: Any) -> None:
        assert rejected(body) == [{"field": "body", "message": "must be a JSON object"}]

    def test_all_problems_are_reported_together(self) -> None:
        errors = rejected(make_event_payload(quantity=-1, store_id="", event_type="X"))

        assert sorted(error["field"] for error in errors) == ["event_type", "quantity", "store_id"]

    def test_error_items_only_expose_field_and_message(self) -> None:
        errors = rejected(make_event_payload(quantity="secret-value"))

        assert all(set(error) == {"field", "message"} for error in errors)
        assert "secret-value" not in str(errors)
