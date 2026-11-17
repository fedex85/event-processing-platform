"""Error handling for the API. Handlers are shared with the processor (see ``common.errors``)."""

from api.errors.exceptions import (
    AnalyticsQueryError,
    AnalyticsUnavailableError,
    PublishFailedError,
    RateLimitedError,
    UnauthorizedError,
)
from common.errors import AppError, RejectedError, register_error_handlers

__all__ = [
    "AnalyticsQueryError",
    "AnalyticsUnavailableError",
    "AppError",
    "PublishFailedError",
    "RateLimitedError",
    "RejectedError",
    "UnauthorizedError",
    "register_error_handlers",
]
