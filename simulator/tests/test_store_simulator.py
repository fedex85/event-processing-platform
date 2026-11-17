import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from common.events import StockEvent
from simulator.store_simulator import (
    SendResult,
    StoreSimulator,
    Summary,
    http_transport,
    parse_args,
    run,
    validate_base_url,
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

    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "ftp://example.com", "example.com", "http://api.example.com"]
    )
    def test_unsafe_urls_are_rejected(self, url: str) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--api-key", "k", "--url", url])


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "http://[::1]:8080",
            "https://inventory-api-abc.a.run.app",
        ],
    )
    def test_safe_urls_pass(self, url: str) -> None:
        assert validate_base_url(url) == url

    @pytest.mark.parametrize(
        "url",
        ["http://10.0.0.5", "http://inventory.example.com", "file:///tmp/x", "https://", ""],
    )
    def test_unsafe_urls_fail(self, url: str) -> None:
        with pytest.raises(ValueError):
            validate_base_url(url)


class Recorder(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.requests.append(
            {"path": self.path, "key": self.headers.get("X-API-Key"), "body": body}
        )
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "accepted"}).encode())

    def log_message(self, format: str, *args: Any) -> None:
        pass


class Redirector(BaseHTTPRequestHandler):
    location = ""

    def do_POST(self) -> None:
        self.send_response(307)
        self.send_header("Location", self.location)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def target() -> Iterator[ThreadingHTTPServer]:
    Recorder.requests = []
    yield from _serve(Recorder)


@pytest.fixture
def redirector() -> Iterator[ThreadingHTTPServer]:
    yield from _serve(Redirector)


class TestHttpTransport:
    def test_it_posts_json_with_the_api_key(self, target: ThreadingHTTPServer) -> None:
        url = f"http://127.0.0.1:{target.server_address[1]}"

        result = http_transport(url, "secret-key")("/v1/events", {"a": 1})

        assert result.status_code == 202
        assert result.body == {"status": "accepted"}
        assert Recorder.requests == [
            {"path": "/v1/events", "key": "secret-key", "body": b'{"a": 1}'}
        ]

    def test_redirects_are_not_followed_so_the_key_is_not_resent(
        self, target: ThreadingHTTPServer, redirector: ThreadingHTTPServer
    ) -> None:
        Redirector.location = f"http://127.0.0.1:{target.server_address[1]}/stolen"
        url = f"http://127.0.0.1:{redirector.server_address[1]}"

        result = http_transport(url, "secret-key")("/v1/events", {"a": 1})

        assert result.status_code == 307
        assert Recorder.requests == []

    def test_a_connection_failure_is_status_zero(self) -> None:
        result = http_transport("http://127.0.0.1:9", "k", timeout=2)("/v1/events", {})

        assert result.status_code == 0
