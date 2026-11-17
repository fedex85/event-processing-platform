import json
import logging
from typing import Any

import pytest
from flask.testing import FlaskClient

from common.structured_logging import JsonFormatter
from processor.domain.errors import PermanentStorageError, TransientStorageError
from processor.domain.models import AlertType
from processor.tests.factories import encode_data, make_envelope, make_event_payload
from processor.tests.fakes import ScriptedRepository

URL = "/internal/pubsub"


def post(client: FlaskClient, body: Any) -> Any:
    return client.post(URL, json=body)


# --- success ---


def test_a_valid_message_is_processed_and_acknowledged(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    response = post(client, make_envelope())

    assert response.status_code == 204
    assert response.data == b""
    assert [e.event_id for e in repository.events] == ["evt_01J5Z8K9Q2M7"]


def test_the_stored_event_keeps_every_field(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    post(client, make_envelope(make_event_payload(quantity=30, metadata={"region": "asturias"})))

    stored = repository.events[0]
    assert (stored.store_id, stored.sku, stored.quantity) == ("store_014", "SKU-88231", 30)
    assert stored.metadata == {"region": "asturias"}
    assert stored.ingested_at.isoformat() == "2026-11-16T19:40:13+00:00"


def test_alerts_are_created_for_a_low_stock_event(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    response = post(client, make_envelope(make_event_payload(quantity=3, previous_quantity=18)))

    assert response.status_code == 204
    assert {a.alert_type for a in repository.alerts} == {
        AlertType.LOW_STOCK,
        AlertType.RAPID_STOCK_DROP,
    }


def test_a_redelivered_message_is_acknowledged_without_creating_duplicates(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    envelope = make_envelope(make_event_payload(quantity=0, previous_quantity=2))

    first = post(client, envelope)
    second = post(client, envelope)

    assert (first.status_code, second.status_code) == (204, 204)
    assert len(repository.events) == 1
    assert len(repository.alerts) == 1


def test_unknown_envelope_fields_and_attributes_are_tolerated(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    envelope = make_envelope(
        attributes={"schema_version": "1", "trace_id": "abc", "anything": "else"}
    )
    envelope["extra"] = "ignored"
    envelope["message"]["orderingKey"] = "k"

    assert post(client, envelope).status_code == 204


def test_a_message_without_schema_version_is_accepted(client: FlaskClient) -> None:
    assert post(client, make_envelope(attributes={})).status_code == 204


# --- poison messages ---


@pytest.mark.parametrize("body", [None, [], "text", 42])
def test_a_body_that_is_not_an_object_is_rejected(client: FlaskClient, body: Any) -> None:
    response = client.post(URL, json=body)

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_envelope"


def test_a_body_that_is_not_json_is_rejected(client: FlaskClient) -> None:
    response = client.post(URL, data="not json", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_envelope"


@pytest.mark.parametrize("body", [{}, {"message": {}}, {"message": "x"}, {"message": {"data": 5}}])
def test_an_envelope_without_a_usable_message_is_rejected(client: FlaskClient, body: Any) -> None:
    response = post(client, body)

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_envelope"


def test_data_that_is_not_base64_is_rejected(client: FlaskClient) -> None:
    response = post(client, make_envelope(data="***not base64***"))

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_message_data"


def test_data_that_is_not_json_is_rejected_with_field_errors(client: FlaskClient) -> None:
    response = post(client, make_envelope(data=encode_data(b"{not json")))

    assert response.status_code == 400
    assert response.get_json()["status"] == "rejected"


def test_an_invalid_event_is_rejected_with_the_failing_fields(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    payload = make_event_payload(quantity=-1)
    del payload["store_id"]

    response = post(client, make_envelope(payload))

    body = response.get_json()
    assert response.status_code == 400
    assert body["status"] == "rejected"
    assert {e["field"] for e in body["errors"]} == {"store_id", "quantity"}
    assert repository.events == []


def test_the_message_without_ingested_at_is_rejected(client: FlaskClient) -> None:
    payload = make_event_payload()
    del payload["ingested_at"]

    response = post(client, make_envelope(payload))

    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        {"field": "ingested_at", "message": "field is required"}
    ]


def test_an_unsupported_schema_version_is_rejected(client: FlaskClient) -> None:
    response = post(client, make_envelope(attributes={"schema_version": "2"}))

    assert response.status_code == 400
    assert response.get_json()["code"] == "unsupported_schema_version"


def test_rejections_never_echo_the_message_content(client: FlaskClient) -> None:
    payload = make_event_payload(quantity="secret-value")

    response = post(client, make_envelope(payload))

    assert response.status_code == 400
    assert "secret-value" not in response.get_data(as_text=True)


# --- storage failures ---


def test_a_transient_storage_failure_asks_pubsub_to_redeliver(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    repository.fail("lookup", TransientStorageError("BigQuery 503 secret-detail"))

    response = post(client, make_envelope())

    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "storage_unavailable"
    assert "secret-detail" not in response.get_data(as_text=True)


def test_the_redelivery_after_a_transient_failure_succeeds(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    repository.fail("save_event", TransientStorageError("down"))
    envelope = make_envelope(make_event_payload(quantity=0, previous_quantity=2))

    assert post(client, envelope).status_code == 503
    assert post(client, envelope).status_code == 204
    assert len(repository.events) == 1
    assert len(repository.alerts) == 1


def test_a_permanent_storage_failure_is_a_server_error(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    repository.fail("save_event", PermanentStorageError("invalid: stock_events.foo"))

    response = post(client, make_envelope())

    assert response.status_code == 500
    assert response.get_json()["code"] == "storage_error"
    assert "stock_events.foo" not in response.get_data(as_text=True)


def test_an_unexpected_error_does_not_leak_details(
    client: FlaskClient, repository: ScriptedRepository
) -> None:
    repository.fail("lookup", RuntimeError("internal secret"))

    response = post(client, make_envelope())

    assert response.status_code == 500
    assert "internal secret" not in response.get_data(as_text=True)


# --- observability ---


class JsonCollector(logging.Handler):
    """Formats each record as it is emitted, while the request context is still bound."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.formatter = JsonFormatter(service_name="inventory-processor")
        self.entries: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


def test_logs_carry_correlation_ids_and_the_delivery_attempt(client: FlaskClient) -> None:
    envelope = make_envelope(
        attributes={"schema_version": "1", "trace_id": "api-trace-1"}, delivery_attempt=3
    )
    collector = JsonCollector()
    logging.getLogger().addHandler(collector)
    try:
        post(client, envelope)
    finally:
        logging.getLogger().removeHandler(collector)

    [entry] = [e for e in collector.entries if e["message"] == "event_processed"]
    assert entry["event_id"] == "evt_01J5Z8K9Q2M7"
    assert entry["store_id"] == "store_014"
    assert entry["sku"] == "SKU-88231"
    assert entry["message_id"] == "1234567890"
    assert entry["delivery_attempt"] == "3"
    assert entry["origin_trace_id"] == "api-trace-1"
    assert entry["trace_id"]


def test_the_endpoint_only_accepts_post(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 405
