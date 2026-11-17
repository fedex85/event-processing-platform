from datetime import UTC, datetime
from typing import Any

import pytest

from common.events import StockEvent
from simulator.store_simulator import (
    SendResult,
    StoreSimulator,
    Summary,
    parse_args,
    run,
)

FIXED_TIME = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


def make_simulator(seed: int | None = 7, *, stores: int = 3, skus: int = 4) -> StoreSimulator:
    return StoreSimulator(stores=stores, skus=skus, seed=seed, clock=lambda: FIXED_TIME)


class RecordingTransport:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, path: str, payload: dict[str, Any]) -> SendResult:
        self.requests.append((path, payload))
        return SendResult(self.status_code, {})


class TestGeneration:
    def test_every_event_satisfies_the_platform_contract(self) -> None:
        simulator = make_simulator()

        for _ in range(300):
            for event in simulator.next_events():
                StockEvent.model_validate(event)

    def test_each_change_is_followed_by_a_stock_update(self) -> None:
        change, update = make_simulator().next_events()

        assert change["event_type"] in {"SALE", "RESTOCK"}
        assert update["event_type"] == "STOCK_UPDATED"
        assert (change["store_id"], change["sku"]) == (update["store_id"], update["sku"])

    def test_stock_updates_chain_and_never_go_negative(self) -> None:
        simulator = make_simulator(stores=1, skus=1)
        level: int | None = None

        for _ in range(500):
            change, update = simulator.next_events()
            if level is not None:
                assert update["previous_quantity"] == level
            sign = -1 if change["event_type"] == "SALE" else 1
            assert update["quantity"] == update["previous_quantity"] + sign * change["quantity"]
            assert update["quantity"] >= 0
            level = update["quantity"]

    def test_the_same_seed_gives_the_same_events(self) -> None:
        first = [make_simulator(seed=42).next_events() for _ in range(1)]
        second = [make_simulator(seed=42).next_events() for _ in range(1)]

        assert first == second

    def test_event_ids_are_unique(self) -> None:
        simulator = make_simulator()
        ids = [e["event_id"] for _ in range(200) for e in simulator.next_events()]

        assert len(ids) == len(set(ids))

    def test_timestamps_are_utc_iso_8601(self) -> None:
        event = make_simulator().next_events()[0]

        assert event["occurred_at"] == "2026-11-17T09:00:00Z"


class TestRun:
    def test_one_request_per_event_by_default(self) -> None:
        transport = RecordingTransport()

        summary = run(make_simulator(), transport, total_events=5)

        assert [path for path, _ in transport.requests] == ["/v1/events"] * 5
        assert summary.events_sent == 5
        assert summary.requests_by_status == {202: 5}
        assert summary.ok

    def test_batches_are_split_into_chunks(self) -> None:
        transport = RecordingTransport()

        summary = run(make_simulator(), transport, total_events=25, batch_size=10)

        assert [path for path, _ in transport.requests] == ["/v1/events:batch"] * 3
        assert [len(payload["events"]) for _, payload in transport.requests] == [10, 10, 5]
        assert summary.events_sent == 25

    def test_exactly_the_requested_number_of_events_is_sent(self) -> None:
        transport = RecordingTransport()

        run(make_simulator(), transport, total_events=7, batch_size=100)

        assert len(transport.requests[0][1]["events"]) == 7

    def test_events_are_generated_when_they_are_sent(self) -> None:
        log: list[str] = []

        def clock() -> datetime:
            log.append("generate")
            return FIXED_TIME

        def transport(path: str, payload: dict[str, Any]) -> SendResult:
            log.append("send")
            return SendResult(202, {})

        run(StoreSimulator(stores=1, skus=1, seed=1, clock=clock), transport, total_events=4)

        assert log == [
            "generate",
            "generate",
            "send",
            "send",
            "generate",
            "generate",
            "send",
            "send",
        ]

    def test_the_rate_limits_how_fast_events_are_sent(self) -> None:
        sleeps: list[float] = []

        run(
            make_simulator(),
            RecordingTransport(),
            total_events=20,
            batch_size=10,
            rate=5,
            sleep=sleeps.append,
        )

        assert sleeps == [2.0, 2.0]

    def test_no_pause_when_the_rate_is_zero(self) -> None:
        sleeps: list[float] = []

        run(make_simulator(), RecordingTransport(), total_events=4, rate=0, sleep=sleeps.append)

        assert sleeps == []

    def test_errors_are_counted_and_make_the_run_fail(self) -> None:
        summary = run(make_simulator(), RecordingTransport(status_code=503), total_events=3)

        assert summary.requests_by_status == {503: 3}
        assert not summary.ok

    def test_an_empty_summary_is_not_ok(self) -> None:
        assert not Summary().ok


class TestArguments:
    def test_an_api_key_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIMULATOR_API_KEY", raising=False)

        with pytest.raises(SystemExit):
            parse_args([])

    def test_the_api_key_can_come_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIMULATOR_API_KEY", "from-env")

        assert parse_args([]).api_key == "from-env"

    def test_defaults(self) -> None:
        args = parse_args(["--api-key", "k"])

        assert (args.url, args.stores, args.skus, args.events, args.batch_size) == (
            "http://127.0.0.1:8080",
            5,
            20,
            100,
            1,
        )

    @pytest.mark.parametrize(
        "flag", [["--batch-size", "0"], ["--batch-size", "101"], ["--events", "0"]]
    )
    def test_invalid_values_are_rejected(self, flag: list[str]) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--api-key", "k", *flag])
