"""Wiring: builds the objects the routes use and makes them injectable."""

from dataclasses import dataclass
from typing import cast

from flask import current_app

from api.config import ApiSettings
from api.middleware.auth import ApiKeyAuthenticator
from api.middleware.rate_limit import TokenBucketRateLimiter
from api.publishers import EventPublisher, build_publisher
from api.services.idempotency import InMemoryIdempotencyStore
from api.services.ingestion import IngestionService


@dataclass(frozen=True)
class Dependencies:
    ingestion: IngestionService
    authenticator: ApiKeyAuthenticator
    rate_limiter: TokenBucketRateLimiter
    max_batch_size: int


def build_dependencies(
    settings: ApiSettings, *, publisher: EventPublisher | None = None
) -> Dependencies:
    """Create the production wiring. Tests pass their own ``publisher``."""
    return Dependencies(
        ingestion=IngestionService(
            publisher=publisher or build_publisher(settings),
            idempotency=InMemoryIdempotencyStore(
                ttl_seconds=settings.idempotency_ttl_seconds,
                max_entries=settings.idempotency_max_entries,
            ),
        ),
        authenticator=ApiKeyAuthenticator(settings.api_key_set),
        rate_limiter=TokenBucketRateLimiter(settings.rate_limit_per_minute),
        max_batch_size=settings.max_batch_size,
    )


def get_dependencies() -> Dependencies:
    return cast(Dependencies, current_app.extensions["dependencies"])
