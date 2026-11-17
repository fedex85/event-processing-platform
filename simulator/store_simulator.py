"""Store simulator: generates realistic stock events and sends them to the API.

Standard library only, so it runs anywhere Python does::

    python -m simulator.store_simulator --api-key local-dev-key-change-me --events 200

Event semantics follow the platform contract:

* ``SALE``          ``quantity`` is the number of units sold.
* ``RESTOCK``       ``quantity`` is the number of units added.
* ``STOCK_UPDATED`` ``quantity`` is the resulting stock and ``previous_quantity`` the stock before.

Every sale or restock is followed by a ``STOCK_UPDATED`` for the same product.
"""

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.client import HTTPMessage
from typing import IO, Any

REGIONS = ("asturias", "madrid", "cataluna", "galicia")
SOURCE = "store-simulator"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StoreSimulator:
    """Keeps a stock level per (store, SKU) and emits the events that change it."""

    def __init__(
        self,
        *,
        stores: int,
        skus: int,
        seed: int | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._rng = random.Random(seed)
        self._clock = clock
        self._stock: dict[tuple[str, str], int] = {
            (f"store_{store:03d}", f"SKU-{sku:05d}"): self._rng.randint(10, 120)
            for store in range(1, stores + 1)
            for sku in range(1, skus + 1)
        }
        self._keys = list(self._stock)

    def next_events(self) -> list[dict[str, Any]]:
        """One sale or restock plus the stock update it causes."""
        store_id, sku = self._rng.choice(self._keys)
        current = self._stock[(store_id, sku)]

        if current == 0 or self._rng.random() < 0.1:
            units = self._rng.randint(20, 100)
            event_type, new_level = "RESTOCK", current + units
        else:
            units = min(current, self._rng.choice((1, 1, 1, 2, 2, 3, 5)))
            if self._rng.random() < 0.03:  # a rush on one product
                units = max(1, int(current * 0.6))
            event_type, new_level = "SALE", current - units

        self._stock[(store_id, sku)] = new_level
        return [
            self._event(store_id, sku, event_type, units),
            self._event(store_id, sku, "STOCK_UPDATED", new_level, previous_quantity=current),
        ]

    def _event(
        self,
        store_id: str,
        sku: str,
        event_type: str,
        quantity: int,
        *,
        previous_quantity: int | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event_id": str(uuid.UUID(int=self._rng.getrandbits(128), version=4)),
            "store_id": store_id,
            "sku": sku,
            "event_type": event_type,
            "quantity": quantity,
            "unit": "units",
            "occurred_at": self._clock().isoformat().replace("+00:00", "Z"),
            "source": SOURCE,
            "metadata": {
                "region": REGIONS[int(store_id.split("_")[1]) % len(REGIONS)],
                "channel": "physical_store",
            },
        }
        if previous_quantity is not None:
            event["previous_quantity"] = previous_quantity
        return event


@dataclass(frozen=True)
class SendResult:
    status_code: int
    body: dict[str, Any]


Transport = Callable[[str, dict[str, Any]], SendResult]


def validate_base_url(url: str) -> str:
    """Return ``url`` if it is safe to send an API key to, otherwise raise ``ValueError``.

    Only http(s) is allowed, and plain http only for the local machine: over the network the
    key would travel in clear text.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("the URL must start with http:// or https://")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("plain http is only allowed for localhost; use https:// for a remote API")
    return url


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect would resend the X-API-Key header to whatever host the response names."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def http_transport(base_url: str, api_key: str, timeout: float = 10.0) -> Transport:
    """POST JSON to ``base_url`` + path. Network failures become status code 0.

    Redirects are not followed: a 3xx is reported like any other non-2xx status.
    """

    def send(path: str, payload: dict[str, Any]) -> SendResult:
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                return SendResult(response.status, _parse(response.read()))
        except urllib.error.HTTPError as error:
            return SendResult(error.code, _parse(error.read()))
        except urllib.error.URLError as error:
            return SendResult(0, {"error": str(error.reason)})

    return send


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"raw": raw[:200].decode("utf-8", "replace")}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


@dataclass
class Summary:
    events_sent: int = 0
    requests_by_status: Counter[int] = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return bool(self.requests_by_status) and all(
            200 <= status < 300 for status in self.requests_by_status
        )


def run(
    simulator: StoreSimulator,
    transport: Transport,
    *,
    total_events: int,
    batch_size: int = 1,
    rate: float = 0,
    sleep: Callable[[float], None] = time.sleep,
) -> Summary:
    """Send ``total_events`` events, one request per event or per batch.

    ``rate`` is events per second; 0 sends as fast as the API answers.
    """
    summary = Summary()
    pending: list[dict[str, Any]] = []
    while summary.events_sent < total_events:
        size = min(batch_size, total_events - summary.events_sent)
        # Events are generated just before they are sent, so ``occurred_at`` is the
        # real time of the sale rather than the time the run started.
        while len(pending) < size:
            pending.extend(simulator.next_events())
        chunk, pending = pending[:size], pending[size:]

        if batch_size == 1:
            result = transport("/v1/events", chunk[0])
        else:
            result = transport("/v1/events:batch", {"events": chunk})
        summary.requests_by_status[result.status_code] += 1
        summary.events_sent += len(chunk)
        if rate > 0:
            sleep(len(chunk) / rate)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send simulated stock events to inventory-api.")
    # 127.0.0.1 rather than localhost: on Windows, localhost tries IPv6 first and every
    # request waits about two seconds before falling back to IPv4.
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="API base URL")
    # Prefer the environment variable: a command-line value shows up in the process list and
    # in the shell history.
    parser.add_argument("--api-key", default=os.environ.get("SIMULATOR_API_KEY"))
    parser.add_argument("--stores", type=int, default=5)
    parser.add_argument("--skus", type=int, default=20, help="products per store")
    parser.add_argument("--events", type=int, default=100, help="total events to send")
    parser.add_argument("--batch-size", type=int, default=1, help="1 = one request per event")
    parser.add_argument("--rate", type=float, default=10, help="events per second; 0 = no limit")
    parser.add_argument("--seed", type=int, default=None, help="make the run reproducible")
    args = parser.parse_args(argv)
    if not args.api_key:
        parser.error("an API key is required: use --api-key or set SIMULATOR_API_KEY")
    try:
        validate_base_url(args.url)
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.batch_size <= 100:
        parser.error("--batch-size must be between 1 and 100")
    if min(args.stores, args.skus, args.events) < 1:
        parser.error("--stores, --skus and --events must be at least 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    simulator = StoreSimulator(stores=args.stores, skus=args.skus, seed=args.seed)
    summary = run(
        simulator,
        http_transport(args.url, args.api_key),
        total_events=args.events,
        batch_size=args.batch_size,
        rate=args.rate,
    )
    print(f"events sent: {summary.events_sent}")
    for status, count in sorted(summary.requests_by_status.items()):
        print(f"  HTTP {status or 'connection error'}: {count} request(s)")
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
