from flask.testing import FlaskClient


def test_health_returns_ok(client: FlaskClient) -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "inventory-api"}


def test_health_only_accepts_get(client: FlaskClient) -> None:
    response = client.post("/v1/health")

    assert response.status_code == 405
    assert response.get_json()["code"] == "method_not_allowed"
    assert "GET" in response.headers["Allow"]
