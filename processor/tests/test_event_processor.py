from datetime import UTC, datetime

import pytest

from processor.domain.errors import PermanentStorageError, TransientStorageError
from processor.domain.models import AlertType
from processor.rules import RuleConfig
from processor.services.processing import EventProcessor, ProcessOutcome
from processor.tests.factories import make_event
from processor.tests.fakes import ScriptedRepository

NOW = datetime(2026, 11, 16, 19, 41, tzinfo=UTC)


@pytest.fixture
def processor(repository: ScriptedRepository) -> EventProcessor:
    return EventProcessor(repository, repository, RuleConfig(), clock=lambda: NOW)


def test_a_healthy_event_is_stored_without_alerts(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    result = processor.process(make_event(quantity=30, previous_quantity=31))

    assert result.outcome is ProcessOutcome.PROCESSED
    assert result.alerts == ()
    assert len(repository.events) == 1
    assert repository.alerts == []
    assert repository.calls == ["lookup", "save_event"]


def test_alerts_are_stored_with_the_detection_time(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    result = processor.process(make_event(quantity=0, previous_quantity=2))

    assert [a.alert_type for a in result.alerts] == [AlertType.OUT_OF_STOCK]
    assert [a.alert_type for a in repository.alerts] == [AlertType.OUT_OF_STOCK]
    assert repository.alerts[0].detected_at == NOW


def test_alerts_are_written_before_the_event(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    processor.process(make_event(quantity=2, previous_quantity=3))

    assert repository.calls == ["lookup", "save_alerts", "save_event"]


def test_a_duplicate_is_ignored_and_creates_nothing(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    processor.process(make_event(quantity=2, previous_quantity=3))

    result = processor.process(make_event(quantity=2, previous_quantity=3))

    assert result.outcome is ProcessOutcome.DUPLICATE
    assert len(repository.events) == 1
    assert len(repository.alerts) == 1


def test_a_duplicate_does_not_evaluate_rules_or_write(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    processor.process(make_event(quantity=2, previous_quantity=3))
    repository.calls.clear()

    processor.process(make_event(quantity=2, previous_quantity=3))

    assert repository.calls == ["lookup"]


def test_history_from_earlier_events_feeds_the_rapid_drop_rule(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    processor.process(
        make_event(
            event_id="a", quantity=40, previous_quantity=41, occurred_at="2026-11-16T19:35:00Z"
        )
    )

    result = processor.process(make_event(event_id="b", quantity=10, previous_quantity=11))

    assert [a.alert_type for a in result.alerts] == [AlertType.RAPID_STOCK_DROP]
    assert result.alerts[0].details["baseline_source"] == "recent_history"


def test_sales_do_not_raise_stock_alerts(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    result = processor.process(make_event(event_type="SALE", quantity=0, previous_quantity=None))

    assert result.alerts == ()
    assert len(repository.events) == 1


def test_a_failed_lookup_stores_nothing(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    repository.fail("lookup", TransientStorageError("down"))

    with pytest.raises(TransientStorageError):
        processor.process(make_event(quantity=0, previous_quantity=2))

    assert repository.events == [] and repository.alerts == []


def test_a_failed_alert_write_leaves_the_event_unstored_so_the_retry_redoes_everything(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    event = make_event(quantity=0, previous_quantity=2)
    repository.fail("save_alerts", TransientStorageError("down"))

    with pytest.raises(TransientStorageError):
        processor.process(event)
    assert repository.events == []

    result = processor.process(event)  # the redelivery

    assert result.outcome is ProcessOutcome.PROCESSED
    assert len(repository.events) == 1
    assert len(repository.alerts) == 1


def test_a_failed_event_write_is_retried_without_duplicating_alerts(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    event = make_event(quantity=0, previous_quantity=2)
    repository.fail("save_event", TransientStorageError("down"))

    with pytest.raises(TransientStorageError):
        processor.process(event)
    assert len(repository.alerts) == 1  # written before the event failed

    result = processor.process(event)  # the redelivery

    assert result.outcome is ProcessOutcome.PROCESSED
    assert len(repository.events) == 1
    assert len(repository.alerts) == 1  # same alert_id, so still one


def test_permanent_errors_propagate(
    processor: EventProcessor, repository: ScriptedRepository
) -> None:
    repository.fail("save_event", PermanentStorageError("bad schema"))

    with pytest.raises(PermanentStorageError):
        processor.process(make_event())
