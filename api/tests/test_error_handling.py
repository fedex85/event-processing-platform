import logging

import pytest
from flask import Flask, Response, jsonify, request
from flask.testing import FlaskClient

from api.schemas import parse_event
from api.tests.factories import make_event_payload
from common.errors import AppError


@pytest.fixture
def app_with_routes(app: Flask) -> Flask:
    """The real app plus throwaway routes that exercise the error handlers.

    The ingestion route itself arrives in Phase 2.
    """

    @app.post("/test/echo")
    def echo() -> Response:
        event = parse_event(request.get_json())
        return jsonify({"event_id": event.event_id})

    @app.get("/test/boom")
    def boom() -> Response:
        raise RuntimeError("database password is hunter2")

    @app.get("/test/conflict")
    def conflict() -> Response:
        raise AppError("Event already exists", status_code=409, code="duplicate_event")

    @app.get("/test/slow-down")
    def slow_down() -> Response:
        raise AppError("Slow down", status_code=429, code="slow", headers={"Retry-After": "7"})

    return app


@pytest.fixture
def client(app_with_routes: Flask) -> FlaskClient:
    return app_with_routes.test_client()


def test_valid_payload_passes_through(client: FlaskClient) -> None:
    response = client.post("/test/echo", json=make_event_payload())

    assert response.status_code == 200
    assert response.get_json() == {"event_id": "evt_01J5Z8K9Q2M7"}


def test_invalid_payload_returns_structured_rejection(client: FlaskClient) -> None:
    response = client.post("/test/echo", json=make_event_payload(quantity=-5))

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "rejected",
        "errors": [
            {
                "field": "quantity",
                "message": "must be an integer greater than or equal to 0",
            }
        ],
    }


def test_malformed_json_returns_400(client: FlaskClient) -> None:
    response = client.post("/test/echo", data="{not json", content_type="application/json")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["status"] == "error"
    assert response.get_json()["code"] == "bad_request"


def test_wrong_content_type_returns_415(client: FlaskClient) -> None:
    response = client.post("/test/echo", data="quantity=1", content_type="text/plain")

    assert response.status_code == 415
    assert response.get_json()["status"] == "error"


def test_json_array_body_is_rejected(client: FlaskClient) -> None:
    response = client.post("/test/echo", json=[1, 2, 3])

    assert response.status_code == 400
    assert response.get_json()["errors"] == [{"field": "body", "message": "must be a JSON object"}]


def test_unknown_route_returns_json_404(client: FlaskClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["code"] == "not_found"


def test_app_errors_use_their_status_and_code(client: FlaskClient) -> None:
    response = client.get("/test/conflict")

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "code": "duplicate_event",
        "message": "Event already exists",
    }


def test_app_errors_can_set_response_headers(client: FlaskClient) -> None:
    response = client.get("/test/slow-down")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"


def test_unexpected_errors_return_generic_500(client: FlaskClient) -> None:
    response = client.get("/test/boom")

    assert response.status_code == 500
    assert response.get_json() == {
        "status": "error",
        "code": "internal_error",
        "message": "Internal server error",
    }
    assert "hunter2" not in response.get_data(as_text=True)


def test_unexpected_errors_are_logged_with_stack_trace(
    client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        client.get("/test/boom")

    records = [r for r in caplog.records if r.getMessage() == "unhandled_exception"]
    assert len(records) == 1
    assert records[0].exc_info is not None
