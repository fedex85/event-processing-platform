"""Wiring: builds the processor's collaborators and makes them injectable."""

import logging
from dataclasses import dataclass
from typing import cast

from flask import current_app

from processor.config import ProcessorSettings
from processor.repositories import (
    AlertRepository,
    BigQueryRepository,
    EventRepository,
    GoogleBigQueryGateway,
    InMemoryRepository,
)
from processor.services.processing import EventProcessor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dependencies:
    processor: EventProcessor


def build_dependencies(
    settings: ProcessorSettings,
    *,
    events: EventRepository | None = None,
    alerts: AlertRepository | None = None,
) -> Dependencies:
    """Create the production wiring. Tests pass their own repositories."""
    if events is None or alerts is None:
        repository = _build_repository(settings)
        events, alerts = events or repository, alerts or repository
    return Dependencies(
        processor=EventProcessor(events=events, alerts=alerts, rule_config=settings.rule_config)
    )


def _build_repository(settings: ProcessorSettings) -> BigQueryRepository | InMemoryRepository:
    """BigQuery when a project is configured; otherwise in memory (local development only)."""
    if settings.gcp_project_id:
        return BigQueryRepository(
            GoogleBigQueryGateway.from_project(settings.gcp_project_id),
            project_id=settings.gcp_project_id,
            dataset=settings.bq_dataset,
            events_table=settings.bq_events_table,
            alerts_table=settings.bq_alerts_table,
            retry_policy=settings.retry_policy,
            timeout_seconds=settings.bq_timeout_seconds,
        )
    logger.warning("bigquery_not_configured_events_are_only_kept_in_memory")
    return InMemoryRepository()


def get_dependencies() -> Dependencies:
    return cast(Dependencies, current_app.extensions["dependencies"])
