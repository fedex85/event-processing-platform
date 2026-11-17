import logging

import pytest
from flask.testing import FlaskClient

from api.errors.exceptions import UnauthorizedError
from api.middleware.auth import ApiKeyAuthenticator
from api.tests.factories import make_event_payload
from api.tests.fakes import FakePublisher


class TestAuthenticator:
    def test_a_valid_key_returns_a_stable_client_id_that_hides_the_key(self) -> None:
        authenticator = ApiKeyAuthenticator(["secret-key-1"])

        first = authenticator.authenticate("secret-key-1")
        second = authenticator.authenticate("secret-key-1")

        assert first == second
        assert len(first) == 12
        assert "secret" not in first

    def test_different_keys_get_different_client_ids(self) -> None:
        authenticator = ApiKeyAuthenticator(["key-a", "key-b"])

        assert authenticator.authenticate("key-a") != authenticator.authenticate("key-b")

    @pytest.mark.parametrize("presented", [None, "", "wrong", "secret-key-1 ", "SECRET-KEY-1"])
    def test_anything_else_is_rejected(self, presented: str | None) -> None:
        authenticator = ApiKeyAuthenticator(["secret-key-1"])

        with pytest.raises(UnauthorizedError):
            authenticator.authenticate(presented)

    def test_non_ascii_values_are_rejected_without_crashing(self) -> None:
        authenticator = ApiKeyAuthenticator(["secret-key-1"])

        with pytest.raises(UnauthorizedError):
            authenticator.authenticate("clavé-ñ")

    def test_without_configured_keys_nothing_is_accepted(self) -> None:
        with pytest.raises(UnauthorizedError):
            ApiKeyAuthenticator([]).authenticate("anything")


class TestEndpoints:
    @pytest.mark.parametrize("path", ["/v1/events", "/v1/events:batch"])
    def test_missing_key_returns_401(
        self, client: FlaskClient, publisher: FakePublisher, path: str
    ) -> None:
        response = client.post(path, json=make_event_payload())

        assert response.status_code == 401
        assert response.get_json() == {
            "status": "error",
            "code": "unauthorized",
            "message": "Missing or invalid API key",
        }
        assert publisher.messages == []

    @pytest.mark.parametrize("path", ["/v1/events", "/v1/events:batch"])
    def test_wrong_key_returns_401(
        self, client: FlaskClient, publisher: FakePublisher, path: str
    ) -> None:
        response = client.post(path, json=make_event_payload(), headers={"X-API-Key": "nope"})

        assert response.status_code == 401
        assert publisher.messages == []

    def test_authentication_happens_before_the_body_is_read(self, client: FlaskClient) -> None:
        response = client.post("/v1/events", data="{not json", content_type="application/json")

        assert response.status_code == 401

    def test_any_configured_key_works(self, publisher: FakePublisher) -> None:
        from api.app import create_app
        from api.config import ApiSettings
        from api.dependencies import build_dependencies

        settings = ApiSettings(environment="local", api_keys="key-a, key-b")
        app = create_app(settings, dependencies=build_dependencies(settings, publisher=publisher))
        client = app.test_client()

        for key in ("key-a", "key-b"):
            response = client.post(
                "/v1/events",
                json=make_event_payload(event_id=f"evt_{key}"),
                headers={"X-API-Key": key},
            )
            assert response.status_code == 202

    def test_health_does_not_require_a_key(self, client: FlaskClient) -> None:
        assert client.get("/v1/health").status_code == 200

    def test_failures_are_logged_without_the_key(
        self, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            client.post("/v1/events", json={}, headers={"X-API-Key": "leaky-key-123"})

        assert "authentication_failed" in [r.getMessage() for r in caplog.records]
        assert "leaky-key-123" not in str([r.__dict__ for r in caplog.records])
