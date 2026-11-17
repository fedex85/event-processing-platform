from datetime import UTC, datetime, timedelta

import pytest
from flask.testing import FlaskClient

from api.config import ApiSettings
from api.services.event_window import EventTimeWindow
from api.tests.factories import NOW, make_event_payload
from api.tests.fakes import FakePublisher

WINDOW = EventTimeWindow(
    max_age=timedelta(days=30), max_future=timedelta(days=15), clock=lambda: NOW
)


class TestEventTimeWindow:
    @pytest.mark.parametrize(
        "occurred_at",
        [
            NOW,
            NOW - timedelta(days=30),
            NOW + timedelta(days=15),
            datetime(2026, 11, 16, 19, 40, 12, tzinfo=UTC),
        ],
    )
    def test_values_inside_the_window_are_accepted(self, occurred_at: datetime) -> None:
        assert WINDOW.check(occurred_at) is None

    @pytest.mark.parametrize(
        "occurred_at",
        [
            NOW - timedelta(days=30, seconds=1),
            NOW + timedelta(days=15, seconds=1),
            datetime(1999, 1, 1, tzinfo=UTC),
            datetime(9999, 12, 31, tzinfo=UTC),
        ],
    )
    def test_values_outside_the_window_name_the_field(self, occurred_at: datetime) -> None:
        problem = WINDOW.check(occurred_at)

        assert problem is not None
        assert problem.field == "occurred_at"
        assert problem.message == (
            "must be within the last 30 days and at most 15 days in the future"
        )

    def test_without_a_clock_the_real_time_is_used(self) -> None:
        window = EventTimeWindow(max_age=timedelta(days=1), max_future=timedelta(days=1))
        assert window.check(datetime.now(UTC)) is None
        assert window.check(datetime.now(UTC) - timedelta(days=3)) is not None


class TestEndpoints:
    def test_a_stale_event_is_rejected_and_not_published(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        payload = make_event_payload(occurred_at="2026-09-01T10:00:00Z")

        response = client.post("/v1/events", json=payload, headers=auth)

        assert response.status_code == 400
        assert response.get_json() == {
            "status": "rejected",
            "errors": [
                {
                    "field": "occurred_at",
                    "message": "must be within the last 30 days and at most 15 days in the future",
                }
            ],
        }
        assert publisher.calls == 0

    def test_an_event_from_the_far_future_is_rejected(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        payload = make_event_payload(occurred_at="2099-01-01T00:00:00Z")

        response = client.post("/v1/events", json=payload, headers=auth)

        assert response.status_code == 400
        assert publisher.calls == 0

    def test_in_a_batch_only_the_out_of_range_event_is_rejected(
        self, client: FlaskClient, auth: dict[str, str], publisher: FakePublisher
    ) -> None:
        good = make_event_payload(event_id="good")
        stale = make_event_payload(event_id="stale", occurred_at="2020-01-01T00:00:00Z")

        response = client.post("/v1/events:batch", json={"events": [good, stale]}, headers=auth)

        body = response.get_json()
        assert response.status_code == 207
        assert [item["status"] for item in body["results"]] == ["accepted", "rejected"]
        assert body["results"][1]["errors"][0]["field"] == "occurred_at"
        assert publisher.event_ids == ["good"]


class TestSettings:
    def test_defaults_stay_inside_what_bigquery_can_stream(self) -> None:
        settings = ApiSettings(environment="local")

        assert settings.max_event_age_days == 30
        assert settings.max_event_future_days == 15

    @pytest.mark.parametrize(
        ("name", "value"),
        [("max_event_age_days", 31), ("max_event_age_days", 0), ("max_event_future_days", 16)],
    )
    def test_the_window_cannot_exceed_the_streaming_limits(self, name: str, value: int) -> None:
        with pytest.raises(ValueError):
            ApiSettings(environment="local", **{name: value})
