"""Publishing adapters."""

import logging

from api.config import ApiSettings
from api.publishers.base import EventPublisher, OutgoingMessage, PublishError
from api.publishers.log_only import LogOnlyPublisher
from api.publishers.pubsub import PubSubEventPublisher

logger = logging.getLogger(__name__)

__all__ = [
    "EventPublisher",
    "LogOnlyPublisher",
    "OutgoingMessage",
    "PubSubEventPublisher",
    "PublishError",
    "build_publisher",
]


def build_publisher(settings: ApiSettings) -> EventPublisher:
    """Pub/Sub when a topic is configured; otherwise log-only (local development only)."""
    if settings.pubsub_topic_id and settings.gcp_project_id:
        return PubSubEventPublisher.from_settings(
            project_id=settings.gcp_project_id,
            topic_id=settings.pubsub_topic_id,
            timeout_seconds=settings.pubsub_publish_timeout_seconds,
        )
    logger.warning("pubsub_not_configured_events_are_only_logged")
    return LogOnlyPublisher()
