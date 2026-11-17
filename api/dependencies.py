"""Wiring: builds the objects the routes use and makes them injectable."""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from flask import current_app

from api.config import ApiSettings
from api.middleware.auth import ApiKeyAuthenticator
from api.middleware.rate_limit import TokenBucketRateLimiter
from api.publishers import EventPublisher, build_publisher
from api.repositories import (
    AnalyticsRepository,
    BigQueryAnalyticsRepository,
    EmptyAnalyticsRepository,
)
from api.services.analytics import AnalyticsService
from api.services.idempotency import InMemoryIdempotencyStore
from api.services.ingestion import IngestionService
from common.bigquery import GoogleBigQueryGateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dependencies:
    ingestion: IngestionService
    analytics: AnalyticsService
    authenticator: ApiKeyAuthenticator
    rate_limiter: TokenBucketRateLimiter
    max_batch_size: int


def build_dependencies(
    settings: ApiSettings,
    *,
    publisher: EventPublisher | None = None,
    analytics_repository: AnalyticsRepository | None = None,
) -> Dependencies:
    """Create the production wiring. Tests pass their own adapters."""
    return Dependencies(
        ingestion=IngestionService(
            publisher=publisher or build_publisher(settings),
            idempotency=InMemoryIdempotencyStore(
                ttl_seconds=settings.idempotency_ttl_seconds,
                max_entries=settings.idempotency_max_entries,
            ),
        ),
        analytics=AnalyticsService(
            analytics_repository or _build_analytics_repository(settings),
            alerts_lookback=timedelta(days=settings.alerts_default_lookback_days),
            trends_lookback=timedelta(hours=settings.trends_default_lookback_hours),
            trends_max_range=timedelta(days=settings.trends_max_range_days),
        ),
        authenticator=ApiKeyAuthenticator(settings.api_key_set),
        rate_limiter=TokenBucketRateLimiter(settings.rate_limit_per_minute),
        max_batch_size=settings.max_batch_size,
    )


def _build_analytics_repository(settings: ApiSettings) -> AnalyticsRepository:
    """BigQuery when a project is configured; otherwise empty results (local development only)."""
    if settings.gcp_project_id:
        return BigQueryAnalyticsRepository(
            GoogleBigQueryGateway.from_project(settings.gcp_project_id),
            project_id=settings.gcp_project_id,
            dataset=settings.bq_dataset,
            alerts_table=settings.bq_alerts_table,
            trends_view=settings.bq_trends_view,
            retry_policy=settings.retry_policy,
            timeout_seconds=settings.bq_timeout_seconds,
        )
    logger.warning("bigquery_not_configured_read_endpoints_return_empty_results")
    return EmptyAnalyticsRepository()


def get_dependencies() -> Dependencies:
    return cast(Dependencies, current_app.extensions["dependencies"])
