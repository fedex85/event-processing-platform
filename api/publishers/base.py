"""The port the ingestion service uses to publish events."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class PublishError(Exception):
    """A message could not be published."""


@dataclass(frozen=True)
class OutgoingMessage:
    event_id: str
    data: bytes
    attributes: Mapping[str, str]


class EventPublisher(Protocol):
    def publish_many(self, messages: Sequence[OutgoingMessage]) -> list[PublishError | None]:
        """Publish messages and wait for the broker to confirm them.

        Returns one entry per message, in order: ``None`` when it was published,
        a ``PublishError`` when it was not. Implementations do not raise for a
        single failed message.
        """
        ...
