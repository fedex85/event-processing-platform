"""BigQuery implementation of the analytics port.

Filters are added to the SQL only when the client supplied them, and every value
travels as a query parameter; the text of the SQL never contains client input.
Table and view names come from settings and are validated at start-up.
"""

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from api.errors.exceptions import AnalyticsQueryError, AnalyticsUnavailableError
from api.repositories.base import AlertFilter, AlertRecord, TrendFilter, TrendRecord
from common.bigquery import BigQueryGateway, QueryParam, is_transient_exception
from common.retry import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9\-:.]{4,61}[a-z0-9]$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


class BigQueryAnalyticsRepository:
    def __init__(
        self,
        gateway: BigQueryGateway,
        *,
        project_id: str,
        dataset: str,
        alerts_table: str,
        trends_view: str,
        retry_policy: RetryPolicy,
        timeout_seconds: float,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError(f"invalid BigQuery project id: {project_id!r}")
        for name in (dataset, alerts_table, trends_view):
            if not _IDENTIFIER_RE.fullmatch(name):
                raise ValueError(f"invalid BigQuery identifier: {name!r}")
        self._gateway = gateway
        self._alerts_table = f"{project_id}.{dataset}.{alerts_table}"
        self._trends_view = f"{project_id}.{dataset}.{trends_view}"
        self._retry_policy = retry_policy
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep

    def find_alerts(self, criteria: AlertFilter) -> list[AlertRecord]:
        conditions = ["detected_at >= @start"]
        parameters: dict[str, QueryParam] = {"start": ("TIMESTAMP", criteria.start)}
        if criteria.end is not None:
            conditions.append("detected_at < @end")
            parameters["end"] = ("TIMESTAMP", criteria.end)
        self._add_equals(
            conditions,
            parameters,
            store_id=criteria.store_id,
            sku=criteria.sku,
            alert_type=criteria.alert_type.value if criteria.alert_type else None,
            severity=criteria.severity.value if criteria.severity else None,
            status=criteria.status.value if criteria.status else None,
        )
        parameters["limit"] = ("INT64", criteria.limit)
        parameters["offset"] = ("INT64", criteria.offset)

        # The window function drops the rare duplicate row that best-effort insertId
        # deduplication let through. WHERE runs first, so partition pruning still applies.
        sql = f"""
            SELECT alert_id, event_id, store_id, sku, alert_type, severity, detected_at,
                   TO_JSON_STRING(details) AS details, status
            FROM `{self._alerts_table}`
            WHERE {" AND ".join(conditions)}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY alert_id ORDER BY detected_at) = 1
            ORDER BY detected_at DESC, alert_id
            LIMIT @limit OFFSET @offset
        """
        rows = self._query("find_alerts", sql, parameters)
        return [
            AlertRecord(
                alert_id=str(row["alert_id"]),
                event_id=str(row["event_id"]),
                store_id=str(row["store_id"]),
                sku=str(row["sku"]),
                alert_type=str(row["alert_type"]),
                severity=str(row["severity"]),
                detected_at=row["detected_at"],
                status=str(row["status"]),
                details=_parse_json_object(row.get("details")),
            )
            for row in rows
        ]

    def find_trends(self, criteria: TrendFilter) -> list[TrendRecord]:
        conditions = ["hour_start >= @start"]
        parameters: dict[str, QueryParam] = {"start": ("TIMESTAMP", criteria.start)}
        if criteria.end is not None:
            conditions.append("hour_start < @end")
            parameters["end"] = ("TIMESTAMP", criteria.end)
        self._add_equals(conditions, parameters, store_id=criteria.store_id, sku=criteria.sku)
        parameters["limit"] = ("INT64", criteria.limit)
        parameters["offset"] = ("INT64", criteria.offset)

        sql = f"""
            SELECT hour_start, store_id, sku, units_sold, units_restocked,
                   avg_stock, event_count, stock_variation
            FROM `{self._trends_view}`
            WHERE {" AND ".join(conditions)}
            ORDER BY hour_start DESC, store_id, sku
            LIMIT @limit OFFSET @offset
        """
        rows = self._query("find_trends", sql, parameters)
        return [
            TrendRecord(
                hour_start=row["hour_start"],
                store_id=str(row["store_id"]),
                sku=str(row["sku"]),
                units_sold=int(row["units_sold"] or 0),
                units_restocked=int(row["units_restocked"] or 0),
                avg_stock=None if row["avg_stock"] is None else float(row["avg_stock"]),
                event_count=int(row["event_count"] or 0),
                stock_variation=(
                    None if row["stock_variation"] is None else int(row["stock_variation"])
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _add_equals(
        conditions: list[str], parameters: dict[str, QueryParam], **filters: str | None
    ) -> None:
        # The column names here are the keyword names above, never client input.
        for column, value in filters.items():
            if value is not None:
                conditions.append(f"{column} = @{column}")
                parameters[column] = ("STRING", value)

    def _query(
        self, description: str, sql: str, parameters: Mapping[str, QueryParam]
    ) -> list[Mapping[str, Any]]:
        retry_kwargs: dict[str, Any] = {} if self._sleep is None else {"sleep": self._sleep}
        try:
            return call_with_retry(
                lambda: self._gateway.query_rows(
                    sql, parameters, timeout_seconds=self._timeout_seconds
                ),
                policy=self._retry_policy,
                is_retryable=is_transient_exception,
                description=description,
                **retry_kwargs,
            )
        except Exception as exc:
            # Details stay in the logs; the client only learns whether to retry.
            logger.error(
                "analytics_query_failed",
                extra={"query": description, "error_type": type(exc).__name__, "error": str(exc)},
            )
            if is_transient_exception(exc):
                raise AnalyticsUnavailableError() from exc
            raise AnalyticsQueryError() from exc


def _parse_json_object(value: Any) -> dict[str, Any]:
    """``TO_JSON_STRING`` yields text; tolerate an already decoded object or a missing value."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def format_timestamp(value: datetime) -> str:
    """ISO 8601 in UTC with a ``Z`` suffix, the format used everywhere in the contract."""
    return value.isoformat().replace("+00:00", "Z")
