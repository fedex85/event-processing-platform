"""OUT_OF_STOCK: the product has no units left."""

from common.events import StockEvent
from processor.domain.models import Alert, AlertType, Severity
from processor.rules.base import RuleContext, build_alert


def check_out_of_stock(event: StockEvent, context: RuleContext) -> Alert | None:
    if event.quantity != 0:
        return None
    return build_alert(
        event,
        context,
        alert_type=AlertType.OUT_OF_STOCK,
        severity=Severity.CRITICAL,
        details={"previous_quantity": event.previous_quantity, "unit": event.unit},
    )
