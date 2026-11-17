import logging
import uuid
from typing import Any

import pytest
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from api.tests.factories import make_event_payload
from api.tests.fakes import FakePublisher
from common.events import IngestedStockEvent

TRACE_ID = "105445aa7843bc8bf206b12000100000"


def post(client: FlaskClient, auth: dict[str, str], payload: Any) -> TestResponse:
    return client.post("/v1/events", json=payload, headers=auth)


class TestAccepted:
    def test_returns_202_and_publishes_the_event(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post(client, auth, make_event_payload())

        assert response.status_code == 202
        body = response.get_json()
        assert body["status"] == "accepted"
        assert body["event_id"] == "evt_01J5Z8K9Q2M7"
        assert body["published_at"].endswith("Z")
        assert "duplicate" not in body
        assert publisher.event_ids == ["evt_01J5Z8K9Q2M7"]

    def test_published_message_is_the_event_plus_ingestion_time(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        post(client, auth, make_event_payload())

        message = IngestedStockEvent.model_validate_json(publisher.messages[0].data)
        assert message.store_id == "store_014"
        assert message.quantity == 3
        assert message.previous_quantity == 18
        assert message.occurred_at.isoformat() == "2026-11-16T19:40:12+00:00"
        assert message.ingested_at.tzinfo is not None
        assert message.metadata == {"region": "asturias", "channel": "physical_store"}

    def test_message_attributes_support_routing_and_tracing(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        client.post(
            "/v1/events",
            json=make_event_payload(),
            headers={**auth, "X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1"},
        )

        assert dict(publisher.messages[0].attributes) == {
            "event_id": "evt_01J5Z8K9Q2M7",
            "store_id": "store_014",
            "sku": "SKU-88231",
            "event_type": "STOCK_UPDATED",
            "schema_version": "1",
            "trace_id": TRACE_ID,
        }

    def test_missing_event_id_is_generated(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post(client, auth, make_event_payload(omit=("event_id",)))

        event_id = response.get_json()["event_id"]
        uuid.UUID(event_id)
        assert publisher.event_ids == [event_id]

    def test_acceptance_is_logged(
        self, client: FlaskClient, auth: dict[str, str], caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            post(client, auth, make_event_payload())

        assert "event_accepted" in [record.getMessage() for record in caplog.records]


class TestRejected:
    def test_invalid_payload_returns_400_and_publishes_nothing(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post(client, auth, make_event_payload(quantity=-1))

        assert response.status_code == 400
        assert response.get_json() == {
            "status": "rejected",
            "errors": [
                {"field": "quantity", "message": "must be an integer greater than or equal to 0"}
            ],
        }
        assert publisher.messages == []

    def test_malformed_json_returns_400(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = client.post(
            "/v1/events", data="{oops", content_type="application/json", headers=auth
        )

        assert response.status_code == 400
        assert publisher.messages == []

    def test_non_json_content_type_returns_415(
        self, client: FlaskClient, auth: dict[str, str]
    ) -> None:
        response = client.post("/v1/events", data="x=1", content_type="text/plain", headers=auth)

        assert response.status_code == 415

    def test_get_is_not_allowed(self, client: FlaskClient, auth: dict[str, str]) -> None:
        assert client.get("/v1/events", headers=auth).status_code == 405


class TestDuplicates:
    def test_resending_an_event_does_not_publish_it_again(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        first = post(client, auth, make_event_payload())
        second = post(client, auth, make_event_payload())

        assert first.status_code == second.status_code == 202
        assert second.get_json() == {
            "status": "accepted",
            "event_id": "evt_01J5Z8K9Q2M7",
            "duplicate": True,
        }
        assert publisher.event_ids == ["evt_01J5Z8K9Q2M7"]

    def test_different_event_ids_are_both_published(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        post(client, auth, make_event_payload(event_id="evt_a"))
        post(client, auth, make_event_payload(event_id="evt_b"))

        assert publisher.event_ids == ["evt_a", "evt_b"]


class TestPublishFailure:
    def test_returns_503_without_leaking_broker_details(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        publisher.fail_all = True

        response = post(client, auth, make_event_payload())

        assert response.status_code == 503
        assert response.get_json() == {
            "status": "error",
            "code": "publish_failed",
            "message": "The event could not be published; retry later",
        }
        assert "secret-broker-detail" not in response.get_data(as_text=True)

    def test_a_failed_event_can_be_retried(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        publisher.fail_all = True
        post(client, auth, make_event_payload())

        publisher.fail_all = False
        retry = post(client, auth, make_event_payload())

        assert retry.status_code == 202
        assert "duplicate" not in retry.get_json()
        assert publisher.event_ids == ["evt_01J5Z8K9Q2M7"]

    def test_the_failure_is_logged(
        self,
        client: FlaskClient,
        auth: dict[str, str],
        publisher: FakePublisher,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publisher.fail_all = True

        with caplog.at_level(logging.ERROR):
            post(client, auth, make_event_payload())

        record = next(r for r in caplog.records if r.getMessage() == "event_publish_failed")
        assert record.__dict__["event_id"] == "evt_01J5Z8K9Q2M7"
        assert "secret-broker-detail" in record.__dict__["error"]
