import pytest

from processor.domain.models import AlertType, Severity
from processor.rules import RuleConfig
from processor.rules.rapid_drop import check_rapid_drop
from processor.tests.factories import make_context, make_event


def test_detects_a_drop_reported_by_the_event_itself() -> None:
    alert = check_rapid_drop(make_event(quantity=3, previous_quantity=18), make_context())

    assert alert is not None
    assert alert.alert_type is AlertType.RAPID_STOCK_DROP
    assert alert.severity is Severity.HIGH
    assert alert.details["baseline_quantity"] == 18
    assert alert.details["baseline_source"] == "previous_quantity"
    assert alert.details["drop_ratio"] == pytest.approx(0.8333, abs=1e-4)
    assert alert.details["window_minutes"] == 15


def test_detects_a_slow_slide_using_the_recent_history() -> None:
    event = make_event(quantity=9, previous_quantity=10)

    alert = check_rapid_drop(event, make_context(recent_max_quantity=30))

    assert alert is not None
    assert alert.details["baseline_quantity"] == 30
    assert alert.details["baseline_source"] == "recent_history"


def test_uses_the_higher_of_previous_quantity_and_history() -> None:
    event = make_event(quantity=5, previous_quantity=40)

    alert = check_rapid_drop(event, make_context(recent_max_quantity=20))

    assert alert is not None
    assert alert.details["baseline_quantity"] == 40
    assert alert.details["baseline_source"] == "previous_quantity"


def test_the_event_wins_a_tie_between_sources() -> None:
    alert = check_rapid_drop(
        make_event(quantity=2, previous_quantity=20), make_context(recent_max_quantity=20)
    )

    assert alert is not None
    assert alert.details["baseline_source"] == "previous_quantity"


@pytest.mark.parametrize(
    ("quantity", "baseline", "expected"),
    [
        (10, 20, False),  # exactly 50%: the rule needs MORE than 50%
        (9, 20, True),  # 55%
        (11, 20, False),  # 45%
        (0, 20, True),  # 100%
    ],
)
def test_the_drop_must_exceed_the_ratio(quantity: int, baseline: int, expected: bool) -> None:
    event = make_event(quantity=quantity, previous_quantity=baseline)

    assert (check_rapid_drop(event, make_context()) is not None) is expected


def test_stays_quiet_without_any_baseline() -> None:
    event = make_event(quantity=1, previous_quantity=None)

    assert check_rapid_drop(event, make_context(recent_max_quantity=None)) is None


def test_stays_quiet_when_stock_did_not_fall() -> None:
    assert check_rapid_drop(make_event(quantity=50, previous_quantity=20), make_context()) is None
    assert check_rapid_drop(make_event(quantity=20, previous_quantity=20), make_context()) is None


def test_a_baseline_below_the_minimum_is_ignored() -> None:
    # 3 -> 0 is a 100% drop, but only three units: not worth an alert.
    event = make_event(quantity=0, previous_quantity=3)

    assert check_rapid_drop(event, make_context()) is None


def test_the_minimum_baseline_is_inclusive_and_configurable() -> None:
    event = make_event(quantity=0, previous_quantity=4)

    assert check_rapid_drop(event, make_context()) is not None
    strict = make_context(config=RuleConfig(rapid_drop_min_baseline=5))
    assert check_rapid_drop(event, strict) is None


def test_the_ratio_is_configurable() -> None:
    event = make_event(quantity=14, previous_quantity=20)  # 30% drop

    assert check_rapid_drop(event, make_context()) is None
    lenient = make_context(config=RuleConfig(rapid_drop_ratio=0.25))
    assert check_rapid_drop(event, lenient) is not None
