"""Event ingestion endpoints."""

import logging
from typing import Any

from flask import Blueprint, Response, g, jsonify, request

from api.dependencies import get_dependencies
from api.errors.exceptions import PublishFailedError
from api.middleware.guard import authenticate_and_rate_limit
from api.schemas import (
    AcceptedResponse,
    BatchResponse,
    BatchResultItem,
    BatchStatus,
    parse_event,
)
from api.services.ingestion import IngestStatus
from common.errors import RejectedError
from common.events import ErrorItem, StockEvent
from common.structured_logging import bind_context

logger = logging.getLogger(__name__)

events_blueprint = Blueprint("events", __name__, url_prefix="/v1")


events_blueprint.before_request(authenticate_and_rate_limit)


@events_blueprint.post("/events")
def ingest_event() -> tuple[Response, int]:
    event = parse_event(request.get_json())
    bind_context(event_id=event.event_id, store_id=event.store_id, sku=event.sku)

    [outcome] = get_dependencies().ingestion.ingest_many([event], trace_id=g.get("trace_id"))
    if outcome.status is IngestStatus.FAILED:
        raise PublishFailedError()

    if outcome.status is IngestStatus.DUPLICATE:
        logger.info("event_duplicate_skipped")
        body = AcceptedResponse(event_id=outcome.event_id, duplicate=True)
    else:
        logger.info("event_accepted")
        body = AcceptedResponse(event_id=outcome.event_id, published_at=outcome.published_at)
    return jsonify(body.to_json()), 202


@events_blueprint.post("/events:batch")
def ingest_batch() -> tuple[Response, int]:
    dependencies = get_dependencies()
    raw_events = _extract_events(request.get_json(), dependencies.max_batch_size)

    results: dict[int, BatchResultItem] = {}
    valid: list[tuple[int, StockEvent]] = []
    for index, raw in enumerate(raw_events):
        try:
            valid.append((index, parse_event(raw)))
        except RejectedError as exc:
            results[index] = BatchResultItem(
                index=index,
                status="rejected",
                event_id=_event_id_hint(raw),
                errors=exc.errors,
            )

    outcomes = dependencies.ingestion.ingest_many(
        [event for _, event in valid], trace_id=g.get("trace_id")
    )
    for (index, _), outcome in zip(valid, outcomes, strict=True):
        failed = outcome.status is IngestStatus.FAILED
        results[index] = BatchResultItem(
            index=index,
            status=outcome.status.value,
            event_id=outcome.event_id,
            # The broker's error text stays in the logs; clients get a generic message.
            errors=[ErrorItem(field="event", message="could not be published; retry")]
            if failed
            else None,
        )

    items = [results[index] for index in range(len(raw_events))]
    counts = {status: sum(1 for item in items if item.status == status) for status in _STATUSES}
    status_code, status = _summarize(counts, total=len(items))

    logger.info("batch_processed", extra={"total": len(items), **counts})
    body = BatchResponse(
        status=status,
        accepted=counts["accepted"],
        duplicates=counts["duplicate"],
        rejected=counts["rejected"],
        failed=counts["failed"],
        results=items,
    )
    return jsonify(body.to_json()), status_code


_STATUSES = ("accepted", "duplicate", "rejected", "failed")


def _summarize(counts: dict[str, int], *, total: int) -> tuple[int, BatchStatus]:
    """Pick the HTTP status for a batch.

    Any publish failure wins (503) so the client knows to retry. Otherwise the
    batch is accepted (202), partially accepted (207) or fully rejected (400).
    """
    if counts["failed"]:
        return 503, "error"
    if counts["rejected"] == total:
        return 400, "rejected"
    if counts["rejected"]:
        return 207, "partial"
    return 202, "accepted"


def _extract_events(body: Any, max_size: int) -> list[Any]:
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise RejectedError([ErrorItem(field="events", message="must be a JSON array of events")])
    events: list[Any] = body["events"]
    if not 1 <= len(events) <= max_size:
        raise RejectedError(
            [ErrorItem(field="events", message=f"must contain between 1 and {max_size} events")]
        )
    return events


def _event_id_hint(raw: Any) -> str | None:
    """The client's own event_id, when it sent a usable one, to help match rejections."""
    if isinstance(raw, dict) and isinstance(raw.get("event_id"), str):
        return str(raw["event_id"])[:255]
    return None
