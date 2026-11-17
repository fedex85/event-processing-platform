"""Runs every rule against an event."""

from common.events import EventType, StockEvent
from processor.domain.models import Alert
from processor.rules.base import RuleContext
from processor.rules.low_stock import check_low_stock
from processor.rules.out_of_stock import check_out_of_stock
from processor.rules.rapid_drop import check_rapid_drop


def evaluate_rules(event: StockEvent, context: RuleContext) -> list[Alert]:
    """Return the alerts an event triggers.

    Only ``STOCK_UPDATED`` carries a resulting stock level. For ``SALE`` and
    ``RESTOCK`` the quantity is a number of units moved, so judging it as a stock
    level would raise false alerts.
    """
    if event.event_type is not EventType.STOCK_UPDATED:
        return []

    checks = (check_out_of_stock, check_low_stock, check_rapid_drop)
    return [alert for check in checks if (alert := check(event, context)) is not None]
