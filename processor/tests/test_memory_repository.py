from datetime import timedelta

from processor.domain.models import AlertType
from processor.repositories.memory import InMemoryRepository
from processor.rules import evaluate_rules
from processor.tests.factories import OCCURRED_AT, make_context, make_event

WINDOW = timedelta(minutes=15)


def at(minutes_before: int) -> str:
    return (OCCURRED_AT - timedelta(minutes=minutes_before)).isoformat().replace("+00:00", "Z")


def test_an_unknown_event_is_not_a_duplicate() -> None:
    lookup = InMemoryRepository().lookup(make_event(), WINDOW)

    assert lookup.is_duplicate is False
    assert lookup.recent_max_quantity is None


def test_a_stored_event_is_reported_as_duplicate() -> None:
    repo = InMemoryRepository()
    repo.save_event(make_event())

    assert repo.lookup(make_event(), WINDOW).is_duplicate is True


def test_saving_the_same_event_twice_keeps_one_row() -> None:
    repo = InMemoryRepository()

    repo.save_event(make_event())
    repo.save_event(make_event())

    assert len(repo.events) == 1


def test_saving_the_same_alerts_twice_keeps_one_row_each() -> None:
    repo = InMemoryRepository()
    alerts = evaluate_rules(make_event(quantity=0, previous_quantity=20), make_context())

    repo.save_alerts(alerts)
    repo.save_alerts(alerts)

    assert {a.alert_type for a in repo.alerts} == {
        AlertType.OUT_OF_STOCK,
        AlertType.RAPID_STOCK_DROP,
    }
    assert len(repo.alerts) == 2


def test_history_is_the_highest_stock_update_inside_the_window() -> None:
    repo = InMemoryRepository()
    repo.save_event(make_event(event_id="a", quantity=40, occurred_at=at(10)))
    repo.save_event(make_event(event_id="b", quantity=25, occurred_at=at(5)))

    lookup = repo.lookup(make_event(event_id="new", quantity=10), WINDOW)

    assert lookup.recent_max_quantity == 40


def test_history_ignores_events_outside_the_window() -> None:
    repo = InMemoryRepository()
    repo.save_event(make_event(event_id="old", quantity=90, occurred_at=at(16)))
    repo.save_event(make_event(event_id="future", quantity=95, occurred_at=at(-1)))

    assert repo.lookup(make_event(event_id="new"), WINDOW).recent_max_quantity is None


def test_the_window_includes_its_boundaries() -> None:
    repo = InMemoryRepository()
    repo.save_event(make_event(event_id="edge", quantity=33, occurred_at=at(15)))

    assert repo.lookup(make_event(event_id="new"), WINDOW).recent_max_quantity == 33


def test_history_ignores_other_stores_skus_and_event_types() -> None:
    repo = InMemoryRepository()
    repo.save_event(make_event(event_id="s", store_id="store_999", quantity=80, occurred_at=at(1)))
    repo.save_event(make_event(event_id="k", sku="SKU-OTHER", quantity=81, occurred_at=at(2)))
    repo.save_event(
        make_event(
            event_id="t", event_type="SALE", quantity=82, previous_quantity=None, occurred_at=at(3)
        )
    )

    assert repo.lookup(make_event(event_id="new"), WINDOW).recent_max_quantity is None
