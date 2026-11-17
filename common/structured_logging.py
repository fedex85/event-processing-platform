"""Structured JSON logging compatible with Cloud Logging.

Every line is one JSON object. ``severity`` and ``message`` are the fields Cloud
Logging understands, and when a project id is known the trace is attached under
``logging.googleapis.com/trace`` so logs correlate with Cloud Trace.

Correlation fields (``trace_id``, ``event_id``, ``store_id``, ``sku``) are kept
in a ``ContextVar`` and added to every record emitted while they are bound.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

TRACE_FIELD = "logging.googleapis.com/trace"

_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)

# Attributes every LogRecord has; anything else came from ``extra=...``.
_RESERVED_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

_HANDLER_MARK = "_inventory_json_handler"


def bind_context(**fields: str | None) -> None:
    """Add correlation fields to the current context. ``None`` removes a field."""
    current = dict(_context.get() or {})
    for key, value in fields.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    _context.set(current)


def clear_context() -> None:
    _context.set(None)


def get_context() -> dict[str, str]:
    return dict(_context.get() or {})


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service_name: str, project_id: str | None = None) -> None:
        super().__init__()
        self._service_name = service_name
        self._project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "logger": record.name,
            "service": self._service_name,
        }

        context = get_context()
        payload.update(context)
        trace_id = context.get("trace_id")
        if trace_id and self._project_id:
            payload[TRACE_FIELD] = f"projects/{self._project_id}/traces/{trace_id}"

        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRIBUTES and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(*, level: str, service_name: str, project_id: str | None = None) -> None:
    """Send JSON logs to stdout. Safe to call more than once.

    Only the handler installed by a previous call is replaced, so handlers added
    by other code (for example pytest's ``caplog``) are left alone.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name=service_name, project_id=project_id))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(level)

    # The development server logs every access in its own format; the request
    # middleware already logs each request as JSON.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
