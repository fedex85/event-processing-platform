"""Pub/Sub adapter."""

import importlib
import logging
import time
from collections.abc import Sequence
from typing import Any

from api.publishers.base import OutgoingMessage, PublishError

logger = logging.getLogger(__name__)


class PubSubEventPublisher:
    """Publishes messages to one Pub/Sub topic and waits for each confirmation.

    The client is injected so tests can pass a fake. The Pub/Sub client batches
    messages internally, so publishing a whole batch before waiting keeps the
    number of round trips low.
    """

    def __init__(self, client: Any, topic_path: str, *, timeout_seconds: float) -> None:
        self._client = client
        self._topic_path = topic_path
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(
        cls, *, project_id: str, topic_id: str, timeout_seconds: float
    ) -> "PubSubEventPublisher":
        # Imported here so tests and tooling work without Google Cloud libraries or credentials.
        # import_module keeps the type checker out of Google's namespace packages, whose
        # typing differs between installations (``from google.cloud import x`` fails there).
        pubsub_v1 = importlib.import_module("google.cloud.pubsub_v1")

        client = pubsub_v1.PublisherClient()
        return cls(
            client,
            client.topic_path(project_id, topic_id),
            timeout_seconds=timeout_seconds,
        )

    def publish_many(self, messages: Sequence[OutgoingMessage]) -> list[PublishError | None]:
        pending: list[Any] = []
        for message in messages:
            try:
                pending.append(
                    self._client.publish(self._topic_path, message.data, **message.attributes)
                )
            except Exception as exc:
                pending.append(PublishError(f"{type(exc).__name__}: {exc}"))

        # One deadline for the whole call, not one timeout per message.
        deadline = time.monotonic() + self._timeout_seconds
        results: list[PublishError | None] = []
        for item in pending:
            if isinstance(item, PublishError):
                results.append(item)
                continue
            try:
                item.result(timeout=max(0.0, deadline - time.monotonic()))
                results.append(None)
            except Exception as exc:
                results.append(PublishError(f"{type(exc).__name__}: {exc}"))
        return results
