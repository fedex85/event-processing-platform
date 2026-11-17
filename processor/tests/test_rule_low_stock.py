import pytest

from processor.domain.models import AlertStatus, AlertType, Severity
from processor.rules import RuleConfig
from processor.rules.low_stock import check_low_stock
from processor.tests.factories import DETECTED_AT, make_context, make_event


@pytest.mark.parametrize("quantity", [1, 3, 5])
def test_raises_an_alert_at_or_below_the_threshold(quantity: int) -> None:
    alert = check_low_stock(make_event(quantity=quantity), make_context())

    assert alert is not None
    assert alert.alert_type is AlertType.LOW_STOCK
    assert alert.severity is Severity.MEDIUM
    assert alert.status is AlertStatus.OPEN
    assert alert.details == {"quantity": quantity, "threshold": 5, "unit": "units"}


@pytest.mark.parametrize("quantity", [6, 18, 1000])
def test_stays_quiet_above_the_threshold(quantity: int) -> None:
    assert check_low_stock(make_event(quantity=quantity), make_context()) is None


def test_zero_is_left_to_the_out_of_stock_rule() -> None:
    assert check_low_stock(make_event(quantity=0), make_context()) is None


def test_the_threshold_is_configurable() -> None:
    context = make_context(config=RuleConfig(low_stock_threshold=10))

    assert check_low_stock(make_event(quantity=10), context) is not None
    assert check_low_stock(make_event(quantity=11), context) is None


def test_the_alert_carries_the_event_identity_and_detection_time() -> None:
    event = make_event(quantity=2)

    alert = check_low_stock(event, make_context())

    assert alert is not None
    assert (alert.event_id, alert.store_id, alert.sku) == (event.event_id, "store_014", "SKU-88231")
    assert alert.detected_at == DETECTED_AT


def test_the_alert_id_is_stable_for_the_same_event() -> None:
    first = check_low_stock(make_event(quantity=2), make_context())
    second = check_low_stock(make_event(quantity=2), make_context())
    other_event = check_low_stock(make_event(event_id="evt_other", quantity=2), make_context())

    assert first is not None and second is not None and other_event is not None
    assert first.alert_id == second.alert_id
    assert first.alert_id != other_event.alert_id
