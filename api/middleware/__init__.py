"""Request middleware for the API. Authentication and rate limiting arrive in Phase 2."""

from flask import Flask

from common.health import HEALTH_PATH
from common.request_context import register_request_context as _register_request_context


def register_request_context(app: Flask) -> None:
    _register_request_context(app, quiet_paths=frozenset({HEALTH_PATH}))
