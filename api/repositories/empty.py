"""Repository used in local development when BigQuery is not configured."""

from api.repositories.base import AlertFilter, AlertRecord, TrendFilter, TrendRecord


class EmptyAnalyticsRepository:
    """Always answers with no rows, so the endpoints can be exercised without Google Cloud."""

    def find_alerts(self, criteria: AlertFilter) -> list[AlertRecord]:
        return []

    def find_trends(self, criteria: TrendFilter) -> list[TrendRecord]:
        return []
