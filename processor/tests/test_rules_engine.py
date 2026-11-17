import pytest

from processor.domain.models import AlertType
from processor.rules import RuleConfig, evaluate_rules
from processor.tests.factories import make_context, make_event


def types(**event_overrides: object) -> set[AlertType]:
    return {a.alert_type for a in evaluate_rules(make_event(**event_overrides), make_context())}


def test_a_healthy_event_raises_no_alerts() -> None:
    assert evaluate_rules(make_event(quantity=30, previous_quantity=31), make_context()) == []


def test_low_stock_alone() -> None:
    assert types(quantity=4, previous_quantity=5) == {AlertType.LOW_STOCK}


def test_out_of_stock_replaces_low_stock() -> None:
    assert types(quantity=0, previous_quantity=2) == {AlertType.OUT_OF_STOCK}


def test_a_big_drop_to_low_stock_raises_both_alerts() -> None:
    assert types(quantity=3, previous_quantity=18) == {
        AlertType.LOW_STOCK,
        AlertType.RAPID_STOCK_DROP,
    }


def test_a_big_drop_to_zero_raises_out_of_stock_and_rapid_drop() -> None:
    assert types(quantity=0, previous_quantity=18) == {
        AlertType.OUT_OF_STOCK,
        AlertType.RAPID_STOCK_DROP,
    }


@pytest.mark.parametrize("event_type", ["SALE", "RESTOCK"])
def test_sales_and_restocks_are_not_judged_as_stock_levels(event_type: str) -> None:
    # quantity is a number of units moved here, so 0 or 3 must not look like empty shelves.
    assert types(event_type=event_type, quantity=3, previous_quantity=None) == set()
    assert types(event_type=event_type, quantity=0, previous_quantity=None) == set()


def test_history_feeds_the_rapid_drop_rule() -> None:
    event = make_event(quantity=10, previous_quantity=11)

    alerts = evaluate_rules(event, make_context(recent_max_quantity=40))

    assert [a.alert_type for a in alerts] == [AlertType.RAPID_STOCK_DROP]


def test_thresholds_come_from_the_config() -> None:
    context = make_context(config=RuleConfig(low_stock_threshold=20))

    alerts = evaluate_rules(make_event(quantity=15, previous_quantity=16), context)

    assert [a.alert_type for a in alerts] == [AlertType.LOW_STOCK]
