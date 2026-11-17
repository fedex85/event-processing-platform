"""Request parsing and response bodies for the public API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from common.errors import RejectedError
from common.events import ErrorItem, StockEvent, to_error_items


def parse_event(payload: Any) -> StockEvent:
    """Validate a decoded JSON body, raising ``RejectedError`` (HTTP 400) if invalid."""
    try:
        return StockEvent.model_validate(payload)
    except ValidationError as exc:
        raise RejectedError(to_error_items(exc)) from exc


class AcceptedResponse(BaseModel):
    """Body of ``202`` for ``POST /v1/events``."""

    status: Literal["accepted"] = "accepted"
    event_id: str
    published_at: datetime | None = None
    duplicate: bool | None = None

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


BatchStatus = Literal["accepted", "partial", "rejected", "error"]


class BatchResultItem(BaseModel):
    index: int
    status: Literal["accepted", "duplicate", "rejected", "failed"]
    event_id: str | None = None
    errors: list[ErrorItem] | None = None


class BatchResponse(BaseModel):
    """Body of ``POST /v1/events:batch``."""

    status: BatchStatus
    accepted: int
    duplicates: int
    rejected: int
    failed: int
    results: list[BatchResultItem]

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
