import json

import pytest
from flask import Flask, Response, jsonify, request
from flask.testing import FlaskClient

from common.errors import register_error_handlers
from common.hardening import apply_hardening


@pytest.fixture
def client() -> FlaskClient:
    app = Flask(__name__)
    apply_hardening(app, max_request_bytes=2048)
    register_error_handlers(app)

    @app.post("/echo")
    def echo() -> Response:
        return jsonify(request.get_json())

    return app.test_client()


def test_oversized_bodies_are_refused_with_413(client: FlaskClient) -> None:
    response = client.post("/echo", json={"x": "a" * 5000})

    assert response.status_code == 413
    assert response.get_json()["status"] == "error"


def test_bodies_under_the_cap_pass(client: FlaskClient) -> None:
    assert client.post("/echo", json={"x": "ok"}).status_code == 200


def test_responses_are_not_cacheable_and_not_sniffed(client: FlaskClient) -> None:
    response = client.post("/echo", json={})

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_responses_cannot_be_rendered_framed_or_leak_a_referrer(client: FlaskClient) -> None:
    response = client.post("/echo", json={})

    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_absurdly_nested_json_is_a_400_not_a_500(client: FlaskClient) -> None:
    body = "[" * 100_000 + "]" * 100_000
    small = Flask(__name__)
    apply_hardening(small, max_request_bytes=1_048_576)
    register_error_handlers(small)

    @small.post("/echo")
    def echo() -> Response:
        return jsonify(request.get_json())

    response = small.test_client().post("/echo", data=body, content_type="application/json")

    assert response.status_code == 400
    assert json.loads(response.data)["code"] == "bad_request"
