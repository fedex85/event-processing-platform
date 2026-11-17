"""RAPID_STOCK_DROP: stock fell by more than the configured ratio inside the window.

The baseline is the highest level seen just before this event: its own
``previous_quantity`` and the highest ``STOCK_UPDATED`` quantity recorded for the
same store and SKU during the last window. Comparing against the maximum, not the
last value, catches a slow slide made of several small updates.
"""

from common.events import StockEvent
from processor.domain.models import Alert, AlertType, Severity
from processor.rules.base import RuleContext, build_alert


def check_rapid_drop(event: StockEvent, context: RuleContext) -> Alert | None:
    config = context.config
    candidates = {
        "previous_quantity": event.previous_quantity,
        "recent_history": context.recent_max_quantity,
    }
    known = {source: value for source, value in candidates.items() if value is not None}
    if not known:
        return None

    # On a tie the event's own previous_quantity wins: it is the most direct evidence.
    source, baseline = max(known.items(), key=lambda item: item[1])
    if baseline < config.rapid_drop_min_baseline or event.quantity >= baseline:
        return None

    dropped = (baseline - event.quantity) / baseline
    if dropped <= config.rapid_drop_ratio:
        return None

    return build_alert(
        event,
        context,
        alert_type=AlertType.RAPID_STOCK_DROP,
        severity=Severity.HIGH,
        details={
            "quantity": event.quantity,
            "baseline_quantity": baseline,
            "baseline_source": source,
            "drop_ratio": round(dropped, 4),
            "threshold_ratio": config.rapid_drop_ratio,
            "window_minutes": config.rapid_drop_window_minutes,
            "unit": event.unit,
        },
    )
