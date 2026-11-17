"""LOW_STOCK: the stock level is at or below the threshold but not zero.

Zero belongs to ``out_of_stock``; reporting both for the same event would only be noise.
"""

from common.events import StockEvent
from processor.domain.models import Alert, AlertType, Severity
from processor.rules.base import RuleContext, build_alert


def check_low_stock(event: StockEvent, context: RuleContext) -> Alert | None:
    threshold = context.config.low_stock_threshold
    if not 0 < event.quantity <= threshold:
        return None
    return build_alert(
        event,
        context,
        alert_type=AlertType.LOW_STOCK,
        severity=Severity.MEDIUM,
        details={"quantity": event.quantity, "threshold": threshold, "unit": event.unit},
    )
