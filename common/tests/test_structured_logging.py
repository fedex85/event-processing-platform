import json
import logging
import sys
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from common.structured_logging import (
    TRACE_FIELD,
    JsonFormatter,
    bind_context,
    clear_context,
    configure_logging,
    get_context,
)


@pytest.fixture(autouse=True)
def _reset_context() -> Iterator[None]:
    clear_context()
    yield
    clear_context()


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def render(
    message: str = "hello",
    *,
    level: int = logging.INFO,
    project_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    record = logging.LogRecord("test", level, __file__, 1, message, (), None)
    record.__dict__.update(extra)
    formatter = JsonFormatter(service_name="svc", project_id=project_id)
    return json.loads(formatter.format(record))  # type: ignore[no-any-return]


def test_output_is_json_with_cloud_logging_fields() -> None:
    entry = render("hello", level=logging.WARNING)

    assert entry["severity"] == "WARNING"
    assert entry["message"] == "hello"
    assert entry["service"] == "svc"
    assert entry["logger"] == "test"
    assert entry["timestamp"].endswith("+00:00")


def test_message_arguments_are_interpolated() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "stored %s", ("evt_1",), None)

    entry = json.loads(JsonFormatter(service_name="svc").format(record))

    assert entry["message"] == "stored evt_1"


def test_bound_context_is_added_to_every_record() -> None:
    bind_context(trace_id="abc", event_id="evt_1", store_id="store_1", sku="SKU-1")

    entry = render()

    assert entry["trace_id"] == "abc"
    assert entry["event_id"] == "evt_1"
    assert entry["store_id"] == "store_1"
    assert entry["sku"] == "SKU-1"


def test_binding_none_removes_a_field() -> None:
    bind_context(trace_id="abc", event_id="evt_1")
    bind_context(event_id=None)

    assert get_context() == {"trace_id": "abc"}


def test_clear_context_removes_everything() -> None:
    bind_context(trace_id="abc")
    clear_context()

    assert "trace_id" not in render()


def test_trace_is_linked_to_cloud_trace_when_project_is_known() -> None:
    bind_context(trace_id="abc")

    assert render(project_id="my-project")[TRACE_FIELD] == "projects/my-project/traces/abc"


def test_no_cloud_trace_link_without_project() -> None:
    bind_context(trace_id="abc")

    assert TRACE_FIELD not in render()


def test_extra_fields_are_included() -> None:
    entry = render(status_code=202, store_id="store_9")

    assert entry["status_code"] == 202
    assert entry["store_id"] == "store_9"


def test_values_that_are_not_json_serializable_do_not_break_logging() -> None:
    entry = render(thing=object())

    assert entry["thing"].startswith("<object object")


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())

    entry = json.loads(JsonFormatter(service_name="svc").format(record))

    assert "ValueError: boom" in entry["exception"]


def test_context_is_not_shared_with_other_threads() -> None:
    bind_context(trace_id="abc")
    seen: list[dict[str, str]] = []

    thread = threading.Thread(target=lambda: seen.append(get_context()))
    thread.start()
    thread.join()

    assert seen == [{}]


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_is_idempotent() -> None:
    configure_logging(level="INFO", service_name="svc")
    configure_logging(level="DEBUG", service_name="svc")

    marked = [
        h for h in logging.getLogger().handlers if getattr(h, "_inventory_json_handler", False)
    ]
    assert len(marked) == 1
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_keeps_handlers_it_did_not_install() -> None:
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)

    configure_logging(level="INFO", service_name="svc")

    assert other in logging.getLogger().handlers


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_writes_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", service_name="svc")

    logging.getLogger("demo").info("started")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(line)["message"] == "started"
