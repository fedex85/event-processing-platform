import pytest
from flask.testing import FlaskClient

from api.app import create_app
from api.config import ApiSettings
from api.dependencies import build_dependencies
from api.middleware.rate_limit import TokenBucketRateLimiter
from api.tests.factories import make_event_payload
from api.tests.fakes import FakeClock, FakePublisher


class TestTokenBucket:
    def test_requests_up_to_the_capacity_are_allowed(self) -> None:
        limiter = TokenBucketRateLimiter(60, monotonic=FakeClock())

        assert [limiter.acquire("a") for _ in range(60)] == [0.0] * 60

    def test_the_next_request_is_told_how_long_to_wait(self) -> None:
        limiter = TokenBucketRateLimiter(60, monotonic=FakeClock())
        for _ in range(60):
            limiter.acquire("a")

        assert limiter.acquire("a") == pytest.approx(1.0)  # 60/min refills one token per second

    def test_tokens_refill_over_time(self) -> None:
        clock = FakeClock()
        limiter = TokenBucketRateLimiter(60, monotonic=clock)
        for _ in range(60):
            limiter.acquire("a")

        clock.advance(2)

        assert limiter.acquire("a") == 0.0
        assert limiter.acquire("a") == 0.0
        assert limiter.acquire("a") > 0

    def test_the_bucket_never_holds_more_than_its_capacity(self) -> None:
        clock = FakeClock()
        limiter = TokenBucketRateLimiter(5, monotonic=clock)
        limiter.acquire("a")

        clock.advance(3600)

        assert [limiter.acquire("a") for _ in range(5)] == [0.0] * 5
        assert limiter.acquire("a") > 0

    def test_clients_have_independent_limits(self) -> None:
        limiter = TokenBucketRateLimiter(1, monotonic=FakeClock())

        assert limiter.acquire("a") == 0.0
        assert limiter.acquire("a") > 0
        assert limiter.acquire("b") == 0.0


class TestEndpoints:
    @pytest.fixture
    def limited_client(self, publisher: FakePublisher) -> FlaskClient:
        settings = ApiSettings(environment="local", api_keys="test-key", rate_limit_per_minute=2)
        app = create_app(settings, dependencies=build_dependencies(settings, publisher=publisher))
        return app.test_client()

    def test_requests_over_the_limit_get_429_with_retry_after(
        self, limited_client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        statuses = [
            limited_client.post(
                "/v1/events", json=make_event_payload(event_id=f"evt_{n}"), headers=auth
            ).status_code
            for n in range(3)
        ]
        limited = limited_client.post("/v1/events", json=make_event_payload(), headers=auth)

        assert statuses == [202, 202, 429]
        assert limited.status_code == 429
        assert limited.get_json()["code"] == "rate_limited"
        assert int(limited.headers["Retry-After"]) >= 1
        assert len(publisher.messages) == 2

    def test_a_batch_counts_as_one_request(
        self, limited_client: FlaskClient, auth: dict[str, str]
    ) -> None:
        events = [make_event_payload(event_id=f"evt_{n}") for n in range(50)]

        response = limited_client.post("/v1/events:batch", json={"events": events}, headers=auth)

        assert response.status_code == 202

    def test_unauthenticated_requests_do_not_consume_the_limit(
        self, limited_client: FlaskClient, auth: dict[str, str]
    ) -> None:
        for _ in range(5):
            assert limited_client.post("/v1/events", json={}).status_code == 401

        assert (
            limited_client.post("/v1/events", json=make_event_payload(), headers=auth).status_code
            == 202
        )

    def test_health_checks_are_not_limited(self, limited_client: FlaskClient) -> None:
        assert [limited_client.get("/v1/health").status_code for _ in range(10)] == [200] * 10
