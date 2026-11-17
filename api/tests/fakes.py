"""In-memory stand-ins for the adapters the API depends on."""

import json
from collections.abc import Sequence
from typing import Any

from api.publishers.base import OutgoingMessage, PublishError


class FakePublisher:
    """Records published messages; can be told to fail."""

    def __init__(self) -> None:
        self.messages: list[OutgoingMessage] = []
        self.calls = 0
        self.fail_all = False
        self.fail_event_ids: set[str] = set()

    def publish_many(self, messages: Sequence[OutgoingMessage]) -> list[PublishError | None]:
        self.calls += 1
        results: list[PublishError | None] = []
        for message in messages:
            if self.fail_all or message.event_id in self.fail_event_ids:
                results.append(PublishError("broker exploded: secret-broker-detail"))
            else:
                self.messages.append(message)
                results.append(None)
        return results

    @property
    def event_ids(self) -> list[str]:
        return [message.event_id for message in self.messages]

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(message.data) for message in self.messages]


class FakeClock:
    """A controllable replacement for ``time.monotonic``."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
