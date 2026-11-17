"""The ingestion use case: deduplicate, publish and report what happened to each event."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from api.publishers.base import EventPublisher, OutgoingMessage
from api.services.idempotency import IdempotencyStore
from common.events import IngestedStockEvent, StockEvent

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"


class IngestStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True)
class IngestOutcome:
    event_id: str
    status: IngestStatus
    published_at: datetime | None = None
    error: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionService:
    def __init__(
        self,
        publisher: EventPublisher,
        idempotency: IdempotencyStore,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._publisher = publisher
        self._idempotency = idempotency
        self._clock = clock

    def ingest_many(
        self, events: Sequence[StockEvent], *, trace_id: str | None = None
    ) -> list[IngestOutcome]:
        """Ingest events and return one outcome per event, in the same order.

        An event is a duplicate when its id was published recently or appeared
        earlier in the same call. An id is remembered only after Pub/Sub
        confirms it, so a failed publish can always be retried.
        """
        outcomes: dict[int, IngestOutcome] = {}
        first_seen: dict[str, int] = {}
        repeats: dict[int, int] = {}
        to_publish: list[tuple[int, OutgoingMessage]] = []

        for index, event in enumerate(events):
            if event.event_id in first_seen:
                repeats[index] = first_seen[event.event_id]
                continue
            first_seen[event.event_id] = index
            if self._idempotency.contains(event.event_id):
                outcomes[index] = IngestOutcome(event.event_id, IngestStatus.DUPLICATE)
                continue
            to_publish.append((index, self._build_message(event, trace_id)))

        if to_publish:
            errors = self._publisher.publish_many([message for _, message in to_publish])
            published_at = self._clock()
            for (index, message), error in zip(to_publish, errors, strict=True):
                if error is None:
                    self._idempotency.add(message.event_id)
                    outcomes[index] = IngestOutcome(
                        message.event_id, IngestStatus.ACCEPTED, published_at=published_at
                    )
                else:
                    logger.error(
                        "event_publish_failed",
                        extra={"event_id": message.event_id, "error": str(error)},
                    )
                    outcomes[index] = IngestOutcome(
                        message.event_id, IngestStatus.FAILED, error=str(error)
                    )

        for index, original in repeats.items():
            first = outcomes[original]
            if first.status is IngestStatus.FAILED:
                outcomes[index] = IngestOutcome(
                    first.event_id, IngestStatus.FAILED, error=first.error
                )
            else:
                outcomes[index] = IngestOutcome(first.event_id, IngestStatus.DUPLICATE)

        return [outcomes[index] for index in range(len(events))]

    def _build_message(self, event: StockEvent, trace_id: str | None) -> OutgoingMessage:
        ingested = IngestedStockEvent.model_validate(
            {**event.model_dump(), "ingested_at": self._clock()}
        )
        attributes = {
            "event_id": event.event_id,
            "store_id": event.store_id,
            "sku": event.sku,
            "event_type": event.event_type.value,
            "schema_version": SCHEMA_VERSION,
        }
        if trace_id:
            attributes["trace_id"] = trace_id
        return OutgoingMessage(
            event_id=event.event_id,
            data=ingested.model_dump_json().encode("utf-8"),
            attributes=attributes,
        )
