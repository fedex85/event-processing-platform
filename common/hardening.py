"""Protections applied to every Flask service."""

from flask import Flask, Response


def apply_hardening(app: Flask, *, max_request_bytes: int) -> None:
    """Cap the request body and add safe default response headers.

    Werkzeug answers ``413`` as soon as a body exceeds the cap, so an oversized
    request cannot make a worker buffer it in memory.
    """
    app.config["MAX_CONTENT_LENGTH"] = max_request_bytes

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        # Responses carry business data: never let a proxy or browser cache them.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # These services only return JSON: nothing should be rendered, framed or leak a referrer.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
