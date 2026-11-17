"""BigQuery adapter.

Why ``insert_rows_json`` (the streaming ``tabledata.insertAll`` API) and not the
Storage Write API:

* It needs no protobuf descriptors, so the adapter is a thin, readable layer.
* Rows are queryable within seconds, which the duplicate check and the
  rapid-drop history rely on.
* ``insertId`` gives best-effort deduplication (about one minute) on top of the
  explicit duplicate check done before writing.

Limitations to keep in mind:

* ``insertId`` deduplication is best effort. Two instances handling the same
  duplicate at the same instant can both insert; the analytics views must
  deduplicate by ``event_id`` (Phase 4).
* Streaming-buffer rows cannot be changed with ``UPDATE`` or ``DELETE`` for a
  while, so this pipeline only ever appends.
* It is billed per ingested byte, unlike the Storage Write API's free default stream.

All the Google client code is isolated in ``GoogleBigQueryGateway``. The
repository only talks to the ``BigQueryGateway`` port, so its logic is tested
with a fake.
"""

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any, Protocol

from common.events import IngestedStockEvent
from processor.domain.errors import PermanentStorageError, TransientStorageError
from processor.domain.models import Alert, EventLookup, ProcessingStatus
from processor.repositories.retry import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

# (BigQuery type name, value), e.g. ("STRING", "store_014").
QueryParam = tuple[str, Any]
RowErrors = Sequence[Mapping[str, Any]]

_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9\-:.]{4,61}[a-z0-9]$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")

# HTTP statuses that Google documents as worth retrying.
TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
# Row-level reasons from insertAll that are worth retrying. "stopped" only means a
# sibling row in the same request failed, so it says nothing by itself.
TRANSIENT_ROW_REASONS = frozenset({"backendError", "internalError", "timeout", "rateLimitExceeded"})


class BigQueryGateway(Protocol):
    def query_rows(
        self, sql: str, parameters: Mapping[str, QueryParam], *, timeout_seconds: float
    ) -> list[Mapping[str, Any]]: ...

    def insert_rows(
        self,
        table: str,
        rows: Sequence[Mapping[str, Any]],
        row_ids: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RowErrors:
        """Return the per-row errors reported by BigQuery (empty when all rows were accepted)."""
        ...


def is_transient_exception(exc: BaseException) -> bool:
    """True for failures that may succeed on a retry: throttling, 5xx, timeouts, network."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in TRANSIENT_HTTP_CODES
    # requests' connection errors and timeouts derive from OSError. Local file problems
    # (missing or unreadable credentials) are not network trouble and will not heal.
    return isinstance(exc, OSError) and not isinstance(exc, PermissionError | FileNotFoundError)


def classify_row_errors(errors: RowErrors) -> TransientStorageError | PermanentStorageError:
    """Decide from BigQuery's row errors whether the write is worth retrying."""
    reasons: set[str] = set()
    for row in errors:
        for detail in row.get("errors", []):
            reasons.add(str(detail.get("reason", "unknown")))
    meaningful = reasons - {"stopped"}
    summary = ", ".join(sorted(reasons)) or "unknown"
    if meaningful <= TRANSIENT_ROW_REASONS:
        return TransientStorageError(f"BigQuery rejected rows with transient errors: {summary}")
    return PermanentStorageError(f"BigQuery rejected rows: {summary}")


def _is_transient_storage_error(exc: Exception) -> bool:
    return isinstance(exc, TransientStorageError)


class BigQueryRepository:
    """Implements both repository ports on top of a ``BigQueryGateway``."""

    def __init__(
        self,
        gateway: BigQueryGateway,
        *,
        project_id: str,
        dataset: str,
        events_table: str,
        alerts_table: str,
        retry_policy: RetryPolicy,
        timeout_seconds: float,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        # These names are placed inside SQL and table paths, so fail fast on anything odd.
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError(f"invalid BigQuery project id: {project_id!r}")
        for name in (dataset, events_table, alerts_table):
            if not _IDENTIFIER_RE.fullmatch(name):
                raise ValueError(f"invalid BigQuery identifier: {name!r}")
        self._gateway = gateway
        self._events_table = f"{project_id}.{dataset}.{events_table}"
        self._alerts_table = f"{project_id}.{dataset}.{alerts_table}"
        self._retry_policy = retry_policy
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep

    # --- EventRepository ---

    def lookup(self, event: IngestedStockEvent, window: timedelta) -> EventLookup:
        # One query answers both questions. Filtering on occurred_at prunes partitions,
        # and clustering on store_id, sku keeps the scan small. The window ends at the
        # event's own occurred_at, so a resent duplicate falls inside it.
        sql = f"""
            SELECT
              COUNTIF(event_id = @event_id) AS seen,
              MAX(IF(event_type = 'STOCK_UPDATED', quantity, NULL)) AS recent_max_quantity
            FROM `{self._events_table}`
            WHERE occurred_at BETWEEN @window_start AND @occurred_at
              AND store_id = @store_id
              AND sku = @sku
        """
        parameters: dict[str, QueryParam] = {
            "event_id": ("STRING", event.event_id),
            "store_id": ("STRING", event.store_id),
            "sku": ("STRING", event.sku),
            "occurred_at": ("TIMESTAMP", event.occurred_at),
            "window_start": ("TIMESTAMP", event.occurred_at - window),
        }
        rows = self._call(
            "bigquery_lookup",
            lambda: self._gateway.query_rows(
                sql, parameters, timeout_seconds=self._timeout_seconds
            ),
        )
        row = rows[0] if rows else {}
        recent = row.get("recent_max_quantity")
        return EventLookup(
            is_duplicate=int(row.get("seen") or 0) > 0,
            recent_max_quantity=int(recent) if recent is not None else None,
        )

    def save_event(self, event: IngestedStockEvent) -> None:
        self._insert(self._events_table, [event_to_row(event)], [event.event_id])

    # --- AlertRepository ---

    def save_alerts(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        self._insert(
            self._alerts_table,
            [alert_to_row(alert) for alert in alerts],
            [alert.alert_id for alert in alerts],
        )

    # --- internals ---

    def _insert(self, table: str, rows: list[dict[str, Any]], row_ids: list[str]) -> None:
        def attempt() -> None:
            errors = self._gateway.insert_rows(
                table, rows, row_ids, timeout_seconds=self._timeout_seconds
            )
            if errors:
                failure = classify_row_errors(errors)
                logger.error(
                    "bigquery_row_errors",
                    extra={
                        "table": table,
                        "failed_rows": len(errors),
                        "reasons": sorted(
                            {
                                str(d.get("reason", "unknown"))
                                for row in errors
                                for d in row.get("errors", [])
                            }
                        ),
                    },
                )
                raise failure

        self._call("bigquery_insert", attempt)

    def _call[T](self, description: str, operation: Callable[[], T]) -> T:
        def guarded() -> T:
            try:
                return operation()
            except (TransientStorageError, PermanentStorageError):
                raise
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if is_transient_exception(exc):
                    raise TransientStorageError(message) from exc
                raise PermanentStorageError(message) from exc

        kwargs: dict[str, Any] = {} if self._sleep is None else {"sleep": self._sleep}
        return call_with_retry(
            guarded,
            policy=self._retry_policy,
            is_retryable=_is_transient_storage_error,
            description=description,
            **kwargs,
        )


def event_to_row(event: IngestedStockEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "store_id": event.store_id,
        "sku": event.sku,
        "event_type": event.event_type.value,
        "quantity": event.quantity,
        "previous_quantity": event.previous_quantity,
        "unit": event.unit,
        "occurred_at": event.occurred_at.isoformat(),
        "ingested_at": event.ingested_at.isoformat(),
        "source": event.source,
        # JSON columns are written as a JSON-encoded string through the streaming API.
        "metadata": json.dumps(event.metadata, ensure_ascii=False),
        "processing_status": ProcessingStatus.PROCESSED.value,
    }


def alert_to_row(alert: Alert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "event_id": alert.event_id,
        "store_id": alert.store_id,
        "sku": alert.sku,
        "alert_type": alert.alert_type.value,
        "severity": alert.severity.value,
        "detected_at": alert.detected_at.isoformat(),
        "details": json.dumps(alert.details, ensure_ascii=False),
        "status": alert.status.value,
    }


class GoogleBigQueryGateway:
    """The only place that touches ``google.cloud.bigquery``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_project(cls, project_id: str) -> "GoogleBigQueryGateway":
        # Imported here so tests and tooling work without Google Cloud libraries or credentials.
        from google.cloud import bigquery

        return cls(bigquery.Client(project=project_id))

    def query_rows(
        self, sql: str, parameters: Mapping[str, QueryParam], *, timeout_seconds: float
    ) -> list[Mapping[str, Any]]:
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(name, type_name, value)
                for name, (type_name, value) in parameters.items()
            ]
        )
        job = self._client.query(sql, job_config=job_config, timeout=timeout_seconds)
        return [dict(row.items()) for row in job.result(timeout=timeout_seconds)]

    def insert_rows(
        self,
        table: str,
        rows: Sequence[Mapping[str, Any]],
        row_ids: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RowErrors:
        errors: RowErrors = self._client.insert_rows_json(
            table, list(rows), row_ids=list(row_ids), timeout=timeout_seconds
        )
        return errors
