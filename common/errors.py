"""Application errors and the global Flask error handlers.

Every error leaves the service as JSON:

* payload validation problems -> ``{"status": "rejected", "errors": [...]}``
* everything else -> ``{"status": "error", "code": "...", "message": "..."}``

Unexpected exceptions are logged with their stack trace but never echoed to the
client.
"""

import logging
from collections.abc import Mapping

from flask import Flask, Response, jsonify
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from common.events import ErrorItem

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An error with a stable machine-readable code and an HTTP status."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.headers = dict(headers or {})
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class RejectedError(AppError):
    """The request payload failed validation."""

    status_code = 400
    code = "validation_error"

    def __init__(self, errors: list[ErrorItem]) -> None:
        super().__init__("Request payload rejected")
        self.errors = errors


def _error_response(code: str, message: str, status_code: int) -> tuple[Response, int]:
    return jsonify({"status": "error", "code": code, "message": message}), status_code


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(RejectedError)
    def handle_rejected(exc: RejectedError) -> tuple[Response, int]:
        logger.info("payload_rejected", extra={"error_fields": [e.field for e in exc.errors]})
        body = {"status": "rejected", "errors": [e.model_dump() for e in exc.errors]}
        return jsonify(body), exc.status_code

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError) -> tuple[Response, int]:
        level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
        logger.log(level, "app_error", extra={"error_code": exc.code})
        response, status_code = _error_response(exc.code, exc.message, exc.status_code)
        response.headers.update(exc.headers)
        return response, status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException) -> tuple[Response, int]:
        status_code = exc.code or 500
        code = (exc.name or "error").lower().replace(" ", "_")
        response, _ = _error_response(code, exc.description or exc.name, status_code)
        if isinstance(exc, MethodNotAllowed) and exc.valid_methods:
            response.headers["Allow"] = ", ".join(exc.valid_methods)
        return response, status_code

    @app.errorhandler(RecursionError)
    def handle_too_deeply_nested(_exc: RecursionError) -> tuple[Response, int]:
        # The JSON parser hits Python's recursion limit on absurdly nested bodies.
        return _error_response("bad_request", "The request body is too deeply nested", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(_exc: Exception) -> tuple[Response, int]:
        logger.exception("unhandled_exception")
        return _error_response("internal_error", "Internal server error", 500)
