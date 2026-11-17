from api.services.idempotency import InMemoryIdempotencyStore
from api.tests.fakes import FakeClock


def make_store(
    clock: FakeClock, *, ttl_seconds: float = 60, max_entries: int = 100
) -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore(
        ttl_seconds=ttl_seconds, max_entries=max_entries, monotonic=clock
    )


def test_unknown_ids_are_not_contained() -> None:
    assert not make_store(FakeClock()).contains("evt_1")


def test_added_ids_are_contained() -> None:
    store = make_store(FakeClock())

    store.add("evt_1")

    assert store.contains("evt_1")
    assert not store.contains("evt_2")


def test_ids_expire_after_the_ttl() -> None:
    clock = FakeClock()
    store = make_store(clock, ttl_seconds=60)
    store.add("evt_1")

    clock.advance(59)
    assert store.contains("evt_1")

    clock.advance(1)
    assert not store.contains("evt_1")


def test_adding_an_id_again_extends_its_life() -> None:
    clock = FakeClock()
    store = make_store(clock, ttl_seconds=60)
    store.add("evt_1")
    clock.advance(50)

    store.add("evt_1")
    clock.advance(50)

    assert store.contains("evt_1")


def test_the_oldest_ids_are_dropped_when_the_store_is_full() -> None:
    store = make_store(FakeClock(), max_entries=3)

    for n in range(5):
        store.add(f"evt_{n}")

    assert [store.contains(f"evt_{n}") for n in range(5)] == [False, False, True, True, True]


def test_expired_ids_are_removed_from_memory() -> None:
    clock = FakeClock()
    store = make_store(clock, ttl_seconds=10, max_entries=1000)
    for n in range(50):
        store.add(f"evt_{n}")

    clock.advance(11)
    store.add("fresh")

    assert len(store._expires_at) == 1
