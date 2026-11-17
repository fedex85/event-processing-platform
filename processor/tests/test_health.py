from flask.testing import FlaskClient


def test_health_returns_ok(client: FlaskClient) -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "inventory-processor"}
    assert response.headers["X-Trace-Id"]


def test_unknown_route_returns_json_404(client: FlaskClient) -> None:
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.get_json()["status"] == "error"
