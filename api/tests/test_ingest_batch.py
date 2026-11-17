import json
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from api.app import create_app
from api.config import ApiSettings
from api.dependencies import build_dependencies
from api.tests.factories import make_event_payload
from api.tests.fakes import FakePublisher


def event(n: int, **overrides: Any) -> dict[str, Any]:
    return make_event_payload(event_id=f"evt_{n}", **overrides)


def post_batch(client: FlaskClient, auth: dict[str, str], body: Any) -> TestResponse:
    # Serialized by hand: the test client treats ``json=None`` as "no body", but JSON ``null``
    # is a case we want to cover.
    return client.post(
        "/v1/events:batch", data=json.dumps(body), content_type="application/json", headers=auth
    )


class TestAccepted:
    def test_all_valid_events_are_published(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(1), event(2), event(3)]})

        assert response.status_code == 202
        body = response.get_json()
        assert body["status"] == "accepted"
        assert (body["accepted"], body["duplicates"], body["rejected"], body["failed"]) == (
            3,
            0,
            0,
            0,
        )
        assert [item["status"] for item in body["results"]] == ["accepted"] * 3
        assert [item["event_id"] for item in body["results"]] == ["evt_1", "evt_2", "evt_3"]
        assert publisher.event_ids == ["evt_1", "evt_2", "evt_3"]

    def test_one_hundred_events_are_accepted(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(n) for n in range(100)]})

        assert response.status_code == 202
        assert len(publisher.messages) == 100

    def test_events_are_published_in_a_single_call(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        post_batch(client, auth, {"events": [event(n) for n in range(10)]})

        assert publisher.calls == 1


class TestPartiallyRejected:
    def test_valid_events_are_published_and_invalid_ones_reported(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        events = [event(1), event(2, quantity=-1), event(3), event(4, store_id="")]

        response = post_batch(client, auth, {"events": events})

        assert response.status_code == 207
        body = response.get_json()
        assert body["status"] == "partial"
        assert (body["accepted"], body["rejected"]) == (2, 2)
        assert body["results"][1] == {
            "index": 1,
            "status": "rejected",
            "event_id": "evt_2",
            "errors": [
                {"field": "quantity", "message": "must be an integer greater than or equal to 0"}
            ],
        }
        assert body["results"][3]["errors"] == [
            {"field": "store_id", "message": "must not be empty"}
        ]
        assert [item["status"] for item in body["results"]] == [
            "accepted",
            "rejected",
            "accepted",
            "rejected",
        ]
        assert publisher.event_ids == ["evt_1", "evt_3"]

    def test_a_non_object_entry_is_rejected_not_fatal(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(1), "nope", 7]})

        assert response.status_code == 207
        results = response.get_json()["results"]
        assert results[1] == {
            "index": 1,
            "status": "rejected",
            "errors": [{"field": "body", "message": "must be a JSON object"}],
        }
        assert publisher.event_ids == ["evt_1"]

    def test_all_invalid_returns_400(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(1, quantity=-1), event(2, sku="")]})

        assert response.status_code == 400
        body = response.get_json()
        assert body["status"] == "rejected"
        assert body["rejected"] == 2
        assert publisher.calls == 0


class TestBatchShape:
    @pytest.mark.parametrize(
        "body", [[], "x", None, {"evnts": []}, {"events": "x"}, {"events": {}}]
    )
    def test_body_must_contain_an_events_array(
        self, client: FlaskClient, auth: dict[str, str], body: Any
    ) -> None:
        response = post_batch(client, auth, body)

        assert response.status_code == 400
        assert response.get_json() == {
            "status": "rejected",
            "errors": [{"field": "events", "message": "must be a JSON array of events"}],
        }

    def test_empty_batch_is_rejected(self, client: FlaskClient, auth: dict[str, str]) -> None:
        response = post_batch(client, auth, {"events": []})

        assert response.status_code == 400
        assert response.get_json()["errors"] == [
            {"field": "events", "message": "must contain between 1 and 100 events"}
        ]

    def test_more_than_100_events_are_rejected(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(n) for n in range(101)]})

        assert response.status_code == 400
        assert response.get_json()["errors"][0]["message"] == (
            "must contain between 1 and 100 events"
        )
        assert publisher.calls == 0

    def test_the_limit_follows_the_configuration(self, publisher: FakePublisher) -> None:
        settings = ApiSettings(environment="local", api_keys="test-key", max_batch_size=2)
        app: Flask = create_app(
            settings, dependencies=build_dependencies(settings, publisher=publisher)
        )
        headers = {"X-API-Key": "test-key"}

        too_many = app.test_client().post(
            "/v1/events:batch", json={"events": [event(1), event(2), event(3)]}, headers=headers
        )

        assert too_many.status_code == 400
        assert too_many.get_json()["errors"][0]["message"] == "must contain between 1 and 2 events"


class TestDuplicates:
    def test_repeated_ids_inside_a_batch_are_published_once(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        response = post_batch(client, auth, {"events": [event(1), event(2), event(1)]})

        body = response.get_json()
        assert response.status_code == 202
        assert [item["status"] for item in body["results"]] == [
            "accepted",
            "accepted",
            "duplicate",
        ]
        assert (body["accepted"], body["duplicates"]) == (2, 1)
        assert publisher.event_ids == ["evt_1", "evt_2"]

    def test_events_published_earlier_are_reported_as_duplicates(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        post_batch(client, auth, {"events": [event(1)]})

        response = post_batch(client, auth, {"events": [event(1), event(2)]})

        assert [item["status"] for item in response.get_json()["results"]] == [
            "duplicate",
            "accepted",
        ]
        assert publisher.event_ids == ["evt_1", "evt_2"]


class TestPublishFailure:
    def test_failures_return_503_with_per_event_detail(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        publisher.fail_event_ids = {"evt_2"}

        response = post_batch(client, auth, {"events": [event(1), event(2), event(3)]})

        assert response.status_code == 503
        body = response.get_json()
        assert body["status"] == "error"
        assert (body["accepted"], body["failed"]) == (2, 1)
        assert body["results"][1] == {
            "index": 1,
            "status": "failed",
            "event_id": "evt_2",
            "errors": [{"field": "event", "message": "could not be published; retry"}],
        }
        assert "secret-broker-detail" not in response.get_data(as_text=True)

    def test_retrying_the_batch_only_republishes_what_failed(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        publisher.fail_event_ids = {"evt_2"}
        batch = {"events": [event(1), event(2)]}
        post_batch(client, auth, batch)

        publisher.fail_event_ids = set()
        retry = post_batch(client, auth, batch)

        assert retry.status_code == 202
        assert [item["status"] for item in retry.get_json()["results"]] == [
            "duplicate",
            "accepted",
        ]
        assert publisher.event_ids == ["evt_1", "evt_2"]

    def test_failure_outranks_rejections(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        publisher.fail_all = True

        response = post_batch(client, auth, {"events": [event(1), event(2, quantity=-1)]})

        assert response.status_code == 503
