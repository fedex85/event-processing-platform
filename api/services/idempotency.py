"""Best-effort duplicate detection for the API."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol


class IdempotencyStore(Protocol):
    def contains(self, event_id: str) -> bool: ...

    def add(self, event_id: str) -> None: ...


class InMemoryIdempotencyStore:
    """Remembers recently published event ids, per process.

    This is an optimization, not a guarantee: each Cloud Run instance has its own
    memory, and entries expire. It stops obvious client retries from reaching
    Pub/Sub; the processor performs the authoritative deduplication in BigQuery.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._monotonic = monotonic
        self._expires_at: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def contains(self, event_id: str) -> bool:
        with self._lock:
            self._evict_expired()
            return event_id in self._expires_at

    def add(self, event_id: str) -> None:
        with self._lock:
            self._evict_expired()
            self._expires_at[event_id] = self._monotonic() + self._ttl_seconds
            self._expires_at.move_to_end(event_id)
            while len(self._expires_at) > self._max_entries:
                self._expires_at.popitem(last=False)

    def _evict_expired(self) -> None:
        # The TTL is constant, so entries are ordered by expiry: only the front can be stale.
        now = self._monotonic()
        while self._expires_at:
            event_id, expires_at = next(iter(self._expires_at.items()))
            if expires_at > now:
                break
            del self._expires_at[event_id]
