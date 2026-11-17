"""Per-request correlation and access logging for Flask services."""

import logging
import re
import time
from uuid import uuid4

from flask import Flask, Response, g, request

from common.structured_logging import bind_context, clear_context

TRACE_HEADER = "X-Cloud-Trace-Context"
RESPONSE_TRACE_HEADER = "X-Trace-Id"

_TRACE_ID_RE = re.compile(r"[0-9a-fA-F]{32}")

request_logger = logging.getLogger("inventory.request")


def parse_trace_header(value: str | None) -> str | None:
    """Return the trace id from ``X-Cloud-Trace-Context`` (``TRACE/SPAN;o=1``)."""
    if not value:
        return None
    trace_id = value.split("/", 1)[0].strip()
    return trace_id.lower() if _TRACE_ID_RE.fullmatch(trace_id) else None


def register_request_context(app: Flask, *, quiet_paths: frozenset[str] = frozenset()) -> None:
    """Bind a ``trace_id`` for each request and log how it ended.

    Paths in ``quiet_paths`` (health probes) are logged at DEBUG so they do not
    flood the logs.
    """

    @app.before_request
    def start_request() -> None:
        # Worker threads are reused, so never trust what a previous request left.
        clear_context()
        trace_id = parse_trace_header(request.headers.get(TRACE_HEADER)) or uuid4().hex
        g.trace_id = trace_id
        g.started_at = time.perf_counter()
        bind_context(trace_id=trace_id)

    @app.after_request
    def finish_request(response: Response) -> Response:
        response.headers[RESPONSE_TRACE_HEADER] = g.get("trace_id", "")
        started_at = g.get("started_at")
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else None
        level = logging.DEBUG if request.path in quiet_paths else logging.INFO
        request_logger.log(
            level,
            "request_completed",
            extra={
                "http_method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response

    @app.teardown_request
    def end_request(_exc: BaseException | None) -> None:
        clear_context()
