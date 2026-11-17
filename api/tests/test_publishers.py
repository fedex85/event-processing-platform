import logging
from collections.abc import Callable
from typing import Any

import pytest

import api.publishers as publishers_module
from api.config import ApiSettings
from api.publishers import LogOnlyPublisher, PublishError, PubSubEventPublisher, build_publisher
from api.publishers.base import OutgoingMessage

TOPIC = "projects/my-project/topics/stock-events"


class FakeFuture:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.timeouts: list[float | None] = []

    def result(self, timeout: float | None = None) -> str:
        self.timeouts.append(timeout)
        if self._error:
            raise self._error
        return "message-id"


class FakePubSubClient:
    def __init__(self, behavior: Callable[[bytes], FakeFuture] | None = None) -> None:
        self.calls: list[tuple[str, bytes, dict[str, Any]]] = []
        self._behavior = behavior or (lambda data: FakeFuture())

    def publish(self, topic: str, data: bytes, **attributes: Any) -> FakeFuture:
        self.calls.append((topic, data, attributes))
        return self._behavior(data)


def message(n: int) -> OutgoingMessage:
    return OutgoingMessage(
        event_id=f"evt_{n}", data=f"payload-{n}".encode(), attributes={"event_id": f"evt_{n}"}
    )


class TestPubSubEventPublisher:
    def test_messages_are_published_to_the_topic_with_their_attributes(self) -> None:
        client = FakePubSubClient()
        publisher = PubSubEventPublisher(client, TOPIC, timeout_seconds=5)

        results = publisher.publish_many([message(1), message(2)])

        assert results == [None, None]
        assert client.calls == [
            (TOPIC, b"payload-1", {"event_id": "evt_1"}),
            (TOPIC, b"payload-2", {"event_id": "evt_2"}),
        ]

    def test_a_failed_confirmation_becomes_a_publish_error(self) -> None:
        client = FakePubSubClient(
            lambda data: FakeFuture(RuntimeError("quota")) if data == b"payload-2" else FakeFuture()
        )
        publisher = PubSubEventPublisher(client, TOPIC, timeout_seconds=5)

        results = publisher.publish_many([message(1), message(2), message(3)])

        assert results[0] is None
        assert isinstance(results[1], PublishError)
        assert "RuntimeError: quota" in str(results[1])
        assert results[2] is None

    def test_an_error_raised_while_publishing_becomes_a_publish_error(self) -> None:
        def explode(data: bytes) -> FakeFuture:
            raise ValueError("message too large")

        publisher = PubSubEventPublisher(FakePubSubClient(explode), TOPIC, timeout_seconds=5)

        [result] = publisher.publish_many([message(1)])

        assert isinstance(result, PublishError)
        assert "message too large" in str(result)

    def test_all_messages_are_sent_before_waiting_for_confirmations(self) -> None:
        order: list[str] = []

        def behavior(data: bytes) -> FakeFuture:
            order.append("publish")
            return FakeFuture()

        client = FakePubSubClient(behavior)
        publisher = PubSubEventPublisher(client, TOPIC, timeout_seconds=5)

        publisher.publish_many([message(1), message(2), message(3)])

        assert order == ["publish"] * 3

    def test_the_timeout_is_a_shared_deadline(self) -> None:
        futures: list[FakeFuture] = []

        def behavior(data: bytes) -> FakeFuture:
            futures.append(FakeFuture())
            return futures[-1]

        publisher = PubSubEventPublisher(FakePubSubClient(behavior), TOPIC, timeout_seconds=5)

        publisher.publish_many([message(1), message(2)])

        timeouts = [future.timeouts[0] for future in futures]
        assert all(t is not None and 0 <= t <= 5 for t in timeouts)
        assert timeouts[1] <= timeouts[0]  # type: ignore[operator]

    def test_no_messages_means_no_calls(self) -> None:
        client = FakePubSubClient()

        assert PubSubEventPublisher(client, TOPIC, timeout_seconds=5).publish_many([]) == []
        assert client.calls == []


class TestLogOnlyPublisher:
    def test_messages_are_logged_and_reported_as_published(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            results = LogOnlyPublisher().publish_many([message(1), message(2)])

        assert results == [None, None]
        logged = [r for r in caplog.records if r.getMessage() == "event_logged_not_published"]
        assert [r.__dict__["event_id"] for r in logged] == ["evt_1", "evt_2"]
        assert logged[0].__dict__["payload"] == "payload-1"


class TestBuildPublisher:
    def test_local_without_a_topic_uses_the_log_publisher(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            publisher = build_publisher(ApiSettings(environment="local"))

        assert isinstance(publisher, LogOnlyPublisher)
        assert "pubsub_not_configured_events_are_only_logged" in [
            r.getMessage() for r in caplog.records
        ]

    def test_a_configured_topic_uses_pubsub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_from_settings(**kwargs: Any) -> object:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(
            publishers_module.PubSubEventPublisher, "from_settings", fake_from_settings
        )
        settings = ApiSettings(
            environment="local",
            gcp_project_id="my-project",
            pubsub_topic_id="stock-events",
            pubsub_publish_timeout_seconds=3,
        )

        assert build_publisher(settings) is sentinel
        assert captured == {
            "project_id": "my-project",
            "topic_id": "stock-events",
            "timeout_seconds": 3,
        }

    def test_a_topic_without_a_project_falls_back_to_the_log_publisher(self) -> None:
        settings = ApiSettings(environment="local", pubsub_topic_id="stock-events")

        assert isinstance(build_publisher(settings), LogOnlyPublisher)
