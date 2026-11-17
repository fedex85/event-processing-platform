"""Local-development publisher."""

import logging
from collections.abc import Sequence

from api.publishers.base import OutgoingMessage, PublishError

logger = logging.getLogger(__name__)


class LogOnlyPublisher:
    """Logs each message instead of publishing it, so the API runs without Google Cloud.

    Only used when ``ENVIRONMENT=local`` and no Pub/Sub topic is configured.
    """

    def publish_many(self, messages: Sequence[OutgoingMessage]) -> list[PublishError | None]:
        for message in messages:
            logger.info(
                "event_logged_not_published",
                extra={"event_id": message.event_id, "payload": message.data.decode("utf-8")},
            )
        return [None] * len(messages)
