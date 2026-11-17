import pytest

from processor.domain.models import AlertType, Severity
from processor.rules.out_of_stock import check_out_of_stock
from processor.tests.factories import make_context, make_event


def test_raises_a_critical_alert_when_quantity_is_zero() -> None:
    alert = check_out_of_stock(make_event(quantity=0, previous_quantity=4), make_context())

    assert alert is not None
    assert alert.alert_type is AlertType.OUT_OF_STOCK
    assert alert.severity is Severity.CRITICAL
    assert alert.details == {"previous_quantity": 4, "unit": "units"}


def test_works_without_a_previous_quantity() -> None:
    alert = check_out_of_stock(make_event(quantity=0, previous_quantity=None), make_context())

    assert alert is not None
    assert alert.details["previous_quantity"] is None


@pytest.mark.parametrize("quantity", [1, 5, 100])
def test_stays_quiet_when_there_is_stock(quantity: int) -> None:
    assert check_out_of_stock(make_event(quantity=quantity), make_context()) is None


def test_alert_ids_differ_between_alert_types_of_the_same_event() -> None:
    from processor.rules.rapid_drop import check_rapid_drop

    event = make_event(quantity=0, previous_quantity=20)

    out_of_stock = check_out_of_stock(event, make_context())
    rapid_drop = check_rapid_drop(event, make_context())

    assert out_of_stock is not None and rapid_drop is not None
    assert out_of_stock.alert_id != rapid_drop.alert_id
