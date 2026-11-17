"""The JSON schemas Terraform will use must describe exactly what the repository writes."""

import json
from pathlib import Path
from typing import Any

import pytest

from processor.repositories.bigquery import alert_to_row, event_to_row
from processor.rules import evaluate_rules
from processor.tests.factories import make_context, make_event

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "infra" / "schemas"


def load(name: str) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    return schema


@pytest.mark.parametrize(
    ("name", "row"),
    [
        ("stock_events", event_to_row(make_event())),
        (
            "stock_alerts",
            alert_to_row(evaluate_rules(make_event(quantity=2), make_context())[0]),
        ),
    ],
)
def test_the_schema_matches_the_rows_that_are_written(name: str, row: dict[str, Any]) -> None:
    schema = load(name)

    assert [field["name"] for field in schema] == list(row)
    for field in schema:
        if field["mode"] == "REQUIRED":
            assert row[field["name"]] is not None, field["name"]


def test_event_columns_follow_the_documented_model() -> None:
    types = {field["name"]: field["type"] for field in load("stock_events")}

    assert types["quantity"] == "INT64"
    assert types["occurred_at"] == "TIMESTAMP"
    assert types["metadata"] == "JSON"
