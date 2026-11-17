"""BigQuery access shared by both services.

Only this module touches ``google.cloud.bigquery``. Everything else talks to the
``BigQueryGateway`` port, so repositories are tested with a fake gateway and need
no Google Cloud libraries or credentials.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

# (BigQuery type name, value), e.g. ("STRING", "store_014").
QueryParam = tuple[str, Any]
RowErrors = Sequence[Mapping[str, Any]]

# HTTP statuses that Google documents as worth retrying.
TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})


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
