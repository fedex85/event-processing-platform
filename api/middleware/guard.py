"""Authentication and rate limiting shared by every ``/v1`` data endpoint."""

import logging

from flask import g, request

from api.dependencies import get_dependencies
from api.errors.exceptions import RateLimitedError
from api.middleware.auth import API_KEY_HEADER
from common.structured_logging import bind_context

logger = logging.getLogger(__name__)


def authenticate_and_rate_limit() -> None:
    """Register with ``blueprint.before_request``.

    Authentication comes first so unauthenticated traffic never consumes a client's quota.
    """
    dependencies = get_dependencies()
    client_id = dependencies.authenticator.authenticate(request.headers.get(API_KEY_HEADER))
    g.client_id = client_id
    bind_context(client_id=client_id)

    retry_after = dependencies.rate_limiter.acquire(client_id)
    if retry_after > 0:
        logger.warning("rate_limited", extra={"retry_after_seconds": round(retry_after, 2)})
        raise RateLimitedError(retry_after)
