from datetime import UTC, datetime

from api.schemas import parse_event
from api.services.idempotency import InMemoryIdempotencyStore
from api.services.ingestion import IngestionService, IngestStatus
from api.tests.factories import make_event_payload
from api.tests.fakes import FakePublisher
from common.events import StockEvent

NOW = datetime(2026, 11, 17, 8, 30, tzinfo=UTC)


def make_service(publisher: FakePublisher) -> IngestionService:
    return IngestionService(
        publisher,
        InMemoryIdempotencyStore(ttl_seconds=60, max_entries=100),
        clock=lambda: NOW,
    )


def make_event(n: int) -> StockEvent:
    return parse_event(make_event_payload(event_id=f"evt_{n}"))


def test_outcomes_follow_the_order_of_the_input() -> None:
    publisher = FakePublisher()
    service = make_service(publisher)

    outcomes = service.ingest_many([make_event(3), make_event(1), make_event(2)])

    assert [o.event_id for o in outcomes] == ["evt_3", "evt_1", "evt_2"]


def test_accepted_events_carry_the_publish_time() -> None:
    [outcome] = make_service(FakePublisher()).ingest_many([make_event(1)])

    assert outcome.status is IngestStatus.ACCEPTED
    assert outcome.published_at == NOW


def test_the_message_records_when_the_event_was_ingested() -> None:
    publisher = FakePublisher()

    make_service(publisher).ingest_many([make_event(1)])

    assert publisher.payloads[0]["ingested_at"] == "2026-11-17T08:30:00Z"


def test_no_trace_attribute_without_a_trace_id() -> None:
    publisher = FakePublisher()

    make_service(publisher).ingest_many([make_event(1)])

    assert "trace_id" not in publisher.messages[0].attributes


def test_a_repeat_of_a_failed_event_in_the_same_call_also_fails() -> None:
    publisher = FakePublisher()
    publisher.fail_event_ids = {"evt_1"}

    outcomes = make_service(publisher).ingest_many([make_event(1), make_event(1)])

    assert [o.status for o in outcomes] == [IngestStatus.FAILED, IngestStatus.FAILED]


def test_nothing_is_published_for_an_empty_call() -> None:
    publisher = FakePublisher()

    assert make_service(publisher).ingest_many([]) == []
    assert publisher.calls == 0


def test_failed_events_are_not_remembered() -> None:
    publisher = FakePublisher()
    service = make_service(publisher)
    publisher.fail_all = True
    service.ingest_many([make_event(1)])
    publisher.fail_all = False

    [outcome] = service.ingest_many([make_event(1)])

    assert outcome.status is IngestStatus.ACCEPTED
