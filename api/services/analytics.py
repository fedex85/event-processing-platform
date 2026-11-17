"""Read use cases: resolve the time window, query, and paginate."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from api.query_params import AlertQuery, TrendQuery
from api.repositories.base import (
    AlertFilter,
    AlertRecord,
    AnalyticsRepository,
    TrendFilter,
    TrendRecord,
)
from common.errors import RejectedError
from common.events import ErrorItem


@dataclass(frozen=True)
class Window:
    """The time range actually applied. ``end`` is ``None`` when the query had no upper bound."""

    start: datetime
    end: datetime | None


@dataclass(frozen=True)
class AlertsPage:
    items: list[AlertRecord]
    window: Window
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True)
class TrendsPage:
    items: list[TrendRecord]
    window: Window
    limit: int
    offset: int
    has_more: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _floor_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


class AnalyticsService:
    def __init__(
        self,
        repository: AnalyticsRepository,
        *,
        alerts_lookback: timedelta = timedelta(days=7),
        trends_lookback: timedelta = timedelta(hours=24),
        trends_max_range: timedelta = timedelta(days=31),
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repository = repository
        self._alerts_lookback = alerts_lookback
        self._trends_lookback = trends_lookback
        self._trends_max_range = trends_max_range
        self._clock = clock

    def list_alerts(self, query: AlertQuery) -> AlertsPage:
        window = self._resolve_window(query.from_, query.to, self._alerts_lookback)
        # One extra row tells whether another page exists without paying for a COUNT(*).
        rows = self._repository.find_alerts(
            AlertFilter(
                start=window.start,
                end=window.end,
                store_id=query.store_id,
                sku=query.sku,
                alert_type=query.alert_type,
                severity=query.severity,
                status=query.status,
                limit=query.limit + 1,
                offset=query.offset,
            )
        )
        return AlertsPage(
            items=rows[: query.limit],
            window=window,
            limit=query.limit,
            offset=query.offset,
            has_more=len(rows) > query.limit,
        )

    def stock_trends(self, query: TrendQuery) -> TrendsPage:
        window = self._resolve_window(
            query.from_, query.to, self._trends_lookback, max_range=self._trends_max_range
        )
        # Hourly buckets: include the bucket that contains ``from``.
        rows = self._repository.find_trends(
            TrendFilter(
                start=_floor_to_hour(window.start),
                end=window.end,
                store_id=query.store_id,
                sku=query.sku,
                limit=query.limit + 1,
                offset=query.offset,
            )
        )
        return TrendsPage(
            items=rows[: query.limit],
            window=window,
            limit=query.limit,
            offset=query.offset,
            has_more=len(rows) > query.limit,
        )

    def _resolve_window(
        self,
        start: datetime | None,
        end: datetime | None,
        default_lookback: timedelta,
        *,
        max_range: timedelta | None = None,
    ) -> Window:
        now = self._clock()
        resolved_start = start if start is not None else now - default_lookback
        if end is not None and resolved_start >= end:
            raise RejectedError([ErrorItem(field="to", message="must be later than 'from'")])
        if max_range is not None and (end or now) - resolved_start > max_range:
            raise RejectedError(
                [
                    ErrorItem(
                        field="from",
                        message=f"the range must not exceed {max_range.days} days",
                    )
                ]
            )
        return Window(start=resolved_start, end=end)
