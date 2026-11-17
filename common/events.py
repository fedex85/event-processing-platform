"""Stock event contract shared by ``inventory-api`` and ``inventory-processor``.

The contract lives in one place so both services validate exactly the same
payload. Validation is strict on purpose: numbers must be real integers (no
``"3"`` or ``3.0``), timestamps must be ISO 8601 strings with a timezone and
unknown fields are rejected.
"""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic_core import ErrorDetails

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]

# Requires a date, a time and the "T" (or space) separator. This keeps out
# values that pydantic would otherwise coerce, such as "2026-11-16" or the
# numeric string "1700000000" (a Unix timestamp, not ISO 8601).
_ISO_8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must include a timezone offset (e.g. 'Z' or '+01:00')")
    return value.astimezone(UTC)


class EventType(StrEnum):
    STOCK_UPDATED = "STOCK_UPDATED"
    SALE = "SALE"
    RESTOCK = "RESTOCK"


def new_event_id() -> str:
    return str(uuid4())


class StockEvent(BaseModel):
    """A stock change reported by a store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: NonEmptyStr = Field(default_factory=new_event_id)
    store_id: NonEmptyStr
    sku: NonEmptyStr
    event_type: EventType
    quantity: NonNegativeInt
    previous_quantity: NonNegativeInt | None = None
    unit: NonEmptyStr = "units"
    occurred_at: datetime
    source: NonEmptyStr
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", mode="before")
    @classmethod
    def _generate_missing_event_id(cls, value: Any) -> Any:
        # An explicit ``null`` is treated like an omitted ``event_id``.
        return new_event_id() if value is None else value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _require_iso_8601_string(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _ISO_8601_RE.match(value):
            raise ValueError("must be an ISO 8601 timestamp (e.g. 2026-11-16T19:40:12Z)")
        return value

    @field_validator("occurred_at", mode="after")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return _require_utc(value)


class IngestedStockEvent(StockEvent):
    """The message ``inventory-api`` publishes to Pub/Sub: the event plus its ingestion time."""

    ingested_at: datetime

    @field_validator("ingested_at", mode="after")
    @classmethod
    def _ingested_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value)


class ErrorItem(BaseModel):
    """One validation problem, in the shape returned to API clients."""

    field: str
    message: str


_INTEGER_FIELDS = frozenset({"quantity", "previous_quantity"})
_INTEGER_ERROR_TYPES = frozenset(
    {"int_type", "int_parsing", "int_from_float", "greater_than_equal"}
)
_INTEGER_MESSAGE = "must be an integer greater than or equal to 0"
_OBJECT_ERROR_TYPES = frozenset({"model_type", "model_attributes_type", "dict_type"})
_VALUE_ERROR_PREFIX = "Value error, "


def _message_for(field: str, error: ErrorDetails) -> str:
    kind = error["type"]
    if field in _INTEGER_FIELDS and kind in _INTEGER_ERROR_TYPES:
        return _INTEGER_MESSAGE
    if kind == "missing":
        return "field is required"
    if kind == "extra_forbidden":
        return "unknown field"
    if kind in _OBJECT_ERROR_TYPES:
        return "must be a JSON object"
    if kind == "string_type":
        return "must be a string"
    if kind == "string_too_short":
        return "must not be empty"
    if kind == "string_too_long":
        limit = (error.get("ctx") or {}).get("max_length")
        return f"must be at most {limit} characters"
    if kind == "enum":
        return "must be one of: " + ", ".join(member.value for member in EventType)
    message = error["msg"]
    return message.removeprefix(_VALUE_ERROR_PREFIX)


def to_error_items(exc: ValidationError) -> list[ErrorItem]:
    """Convert a pydantic error into stable, client-friendly items.

    Inputs are never echoed back, so a rejected payload cannot leak into
    responses or logs through the error body.
    """
    items: list[ErrorItem] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = error["loc"]
        field = ".".join(str(part) for part in location) if location else "body"
        items.append(ErrorItem(field=field, message=_message_for(field, error)))
    return items
