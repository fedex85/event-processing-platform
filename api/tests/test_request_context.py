import logging
import re

import pytest
from flask.testing import FlaskClient

from common.request_context import parse_trace_header
from common.structured_logging import get_context

TRACE_ID = "105445aa7843bc8bf206b12000100000"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"{TRACE_ID}/1;o=1", TRACE_ID),
        (TRACE_ID, TRACE_ID),
        (f"{TRACE_ID.upper()}/1", TRACE_ID),
        ("garbage", None),
        ("abc123/1", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_trace_header(header: str | None, expected: str | None) -> None:
    assert parse_trace_header(header) == expected


def test_trace_id_is_taken_from_the_cloud_trace_header(client: FlaskClient) -> None:
    response = client.get("/v1/health", headers={"X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1"})

    assert response.headers["X-Trace-Id"] == TRACE_ID


def test_trace_id_is_generated_when_missing_and_differs_per_request(client: FlaskClient) -> None:
    first = client.get("/v1/health").headers["X-Trace-Id"]
    second = client.get("/v1/health").headers["X-Trace-Id"]

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_invalid_trace_header_is_replaced(client: FlaskClient) -> None:
    response = client.get("/v1/health", headers={"X-Cloud-Trace-Context": "nope"})

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Trace-Id"])


def test_context_does_not_leak_after_a_request(client: FlaskClient) -> None:
    client.get("/v1/health")

    assert get_context() == {}


def test_each_request_is_logged(client: FlaskClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="inventory.request"):
        client.get("/does-not-exist")

    [record] = [r for r in caplog.records if r.name == "inventory.request"]
    assert record.levelno == logging.INFO
    assert record.__dict__["http_method"] == "GET"
    assert record.__dict__["path"] == "/does-not-exist"
    assert record.__dict__["status_code"] == 404
    assert record.__dict__["latency_ms"] >= 0


def test_health_checks_are_logged_at_debug(
    client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="inventory.request"):
        client.get("/v1/health")

    [record] = [r for r in caplog.records if r.name == "inventory.request"]
    assert record.levelno == logging.DEBUG
