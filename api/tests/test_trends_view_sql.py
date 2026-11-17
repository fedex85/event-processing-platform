"""Structural checks on the view definition.

BigQuery is not available to the test suite, so these tests cannot prove the SQL runs.
They keep the view and the code that reads it from drifting apart. Verify the SQL itself
with ``bq query --dry_run`` (see docs/runbook.md) before deploying.
"""

import re
from pathlib import Path

VIEW_SQL = Path(__file__).resolve().parents[2] / "infra" / "sql" / "v_stock_trends.sql"

# Columns the API selects from the view (api/repositories/bigquery.py).
API_COLUMNS = [
    "hour_start",
    "store_id",
    "sku",
    "units_sold",
    "units_restocked",
    "avg_stock",
    "event_count",
    "stock_variation",
]


def sql() -> str:
    return VIEW_SQL.read_text()


def test_the_view_exposes_every_column_the_api_reads() -> None:
    text = sql()

    for column in API_COLUMNS:
        assert re.search(rf"\b{column}\b", text), column


def test_the_file_is_a_query_not_a_ddl_statement() -> None:
    """Terraform passes the file as the view's query, so it must not create the view itself."""
    statements = [
        line for line in sql().splitlines() if line.strip() and not line.lstrip().startswith("--")
    ]

    assert statements[0].startswith("WITH ")
    assert "CREATE" not in sql().upper().replace("-- ", "")
    assert not sql().rstrip().endswith(";")


def test_the_view_reads_the_events_table_and_groups_by_hour_store_and_sku() -> None:
    text = sql()

    assert "`${project_id}.${dataset}.stock_events`" in text
    assert "GROUP BY hour_start, store_id, sku" in text
    assert "TIMESTAMP_TRUNC(occurred_at, HOUR) AS hour_start" in text


def test_the_view_deduplicates_events() -> None:
    text = sql()

    assert "PARTITION BY event_id, occurred_at" in text
    assert "= 1" in text


def test_the_view_covers_the_required_measures() -> None:
    text = sql()

    assert "IF(event_type = 'SALE', quantity, 0)) AS units_sold" in text
    assert "IF(event_type = 'RESTOCK', quantity, 0)) AS units_restocked" in text
    assert "AS avg_stock" in text
    assert "COUNT(*) AS event_count" in text
    assert "AS stock_variation" in text


def test_every_column_is_present_in_the_events_schema() -> None:
    import json

    schema = json.loads((VIEW_SQL.parents[1] / "schemas" / "stock_events.json").read_text())
    columns = {field["name"] for field in schema}
    used = {"event_id", "occurred_at", "ingested_at", "event_type", "quantity", "previous_quantity"}

    assert used <= columns


def test_only_the_template_placeholders_terraform_provides_are_used() -> None:
    placeholders = set(re.findall(r"\$\{(\w+)\}", sql()))

    assert placeholders == {"project_id", "dataset"}
