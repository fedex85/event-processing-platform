"""Processes one event: deduplicate, apply the rules, store alerts and then the event."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from common.events import IngestedStockEvent
from common.structured_logging import bind_context
from processor.domain.models import Alert
from processor.repositories.base import AlertRepository, EventRepository
from processor.rules import RuleConfig, RuleContext, evaluate_rules

logger = logging.getLogger(__name__)


class ProcessOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class ProcessResult:
    outcome: ProcessOutcome
    alerts: tuple[Alert, ...] = ()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EventProcessor:
    """Business pipeline for one stock event.

    Write order matters. The event row is the commit marker: it is written last,
    and its presence is what makes a redelivery count as a duplicate. So:

    * a failure before the event is stored leaves it unprocessed and the retry
      redoes everything;
    * a failure while storing the event leaves, at worst, alerts that the retry
      writes again with the same ``alert_id`` (no new alerts).

    Storage errors propagate; the caller decides the HTTP answer.
    """

    def __init__(
        self,
        events: EventRepository,
        alerts: AlertRepository,
        rule_config: RuleConfig,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._events = events
        self._alerts = alerts
        self._rule_config = rule_config
        self._clock = clock

    def process(self, event: IngestedStockEvent) -> ProcessResult:
        bind_context(event_id=event.event_id, store_id=event.store_id, sku=event.sku)

        lookup = self._events.lookup(event, self._rule_config.rapid_drop_window)
        if lookup.is_duplicate:
            logger.info("duplicate_event_ignored")
            return ProcessResult(ProcessOutcome.DUPLICATE)

        context = RuleContext(
            config=self._rule_config,
            detected_at=self._clock(),
            recent_max_quantity=lookup.recent_max_quantity,
        )
        alerts = evaluate_rules(event, context)
        if alerts:
            self._alerts.save_alerts(alerts)
        self._events.save_event(event)

        logger.info(
            "event_processed",
            extra={
                "event_type": event.event_type.value,
                "alerts": [alert.alert_type.value for alert in alerts],
            },
        )
        return ProcessResult(ProcessOutcome.PROCESSED, tuple(alerts))
