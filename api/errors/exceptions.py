"""Errors specific to the public API."""

import math

from common.errors import AppError


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self) -> None:
        super().__init__("Missing or invalid API key")


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after_seconds: float) -> None:
        retry_after = max(1, math.ceil(retry_after_seconds))
        super().__init__(
            "Too many requests; retry later",
            headers={"Retry-After": str(retry_after)},
        )
        self.retry_after = retry_after


class PublishFailedError(AppError):
    status_code = 503
    code = "publish_failed"

    def __init__(self) -> None:
        super().__init__("The event could not be published; retry later")
