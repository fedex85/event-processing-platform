from collections.abc import Callable, Iterator

import pytest

from processor.repositories.retry import RetryPolicy, call_with_retry


class BoomError(Exception):
    pass


def run[T](
    operation: Callable[[], T],
    policy: RetryPolicy | None = None,
    *,
    retryable: Callable[[Exception], bool] = lambda e: isinstance(e, BoomError),
    jitter: Callable[[], float] = lambda: 1.0,
) -> tuple[T, list[float]]:
    sleeps: list[float] = []
    result = call_with_retry(
        operation,
        policy=policy or RetryPolicy(attempts=4, base_delay_seconds=0.1, max_delay_seconds=0.5),
        is_retryable=retryable,
        description="test",
        sleep=sleeps.append,
        jitter=jitter,
    )
    return result, sleeps


def test_returns_immediately_when_the_first_attempt_works() -> None:
    result, sleeps = run(lambda: "ok")

    assert result == "ok"
    assert sleeps == []


def test_retries_until_success() -> None:
    attempts: Iterator[Exception | str] = iter([BoomError("1"), BoomError("2"), "done"])

    def operation() -> str:
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    result, sleeps = run(operation)

    assert result == "done"
    assert len(sleeps) == 2


def test_the_wait_doubles_each_time_and_is_capped() -> None:
    def always_fails() -> None:
        raise BoomError

    sleeps: list[float] = []
    with pytest.raises(BoomError):
        call_with_retry(
            always_fails,
            policy=RetryPolicy(attempts=5, base_delay_seconds=0.1, max_delay_seconds=0.5),
            is_retryable=lambda _e: True,
            description="test",
            sleep=sleeps.append,
            jitter=lambda: 1.0,  # no randomness: wait the full ceiling
        )

    assert sleeps == pytest.approx([0.1, 0.2, 0.4, 0.5])


def test_full_jitter_waits_a_fraction_of_the_ceiling() -> None:
    sleeps: list[float] = []

    def always_fails() -> None:
        raise BoomError

    with pytest.raises(BoomError):
        call_with_retry(
            always_fails,
            policy=RetryPolicy(attempts=3, base_delay_seconds=1.0, max_delay_seconds=10.0),
            is_retryable=lambda _e: True,
            description="test",
            sleep=sleeps.append,
            jitter=lambda: 0.25,
        )

    assert sleeps == [0.25, 0.5]


def test_gives_up_after_the_configured_attempts_and_raises_the_last_error() -> None:
    calls: list[int] = []

    def always_fails() -> None:
        calls.append(1)
        raise BoomError(f"attempt {len(calls)}")

    with pytest.raises(BoomError, match="attempt 4"):
        run(always_fails)

    assert len(calls) == 4


def test_does_not_retry_errors_that_are_not_retryable() -> None:
    calls: list[int] = []

    def fails() -> None:
        calls.append(1)
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        run(fails)

    assert len(calls) == 1


def test_one_attempt_means_no_retries() -> None:
    calls: list[int] = []

    def fails() -> None:
        calls.append(1)
        raise BoomError

    with pytest.raises(BoomError):
        run(fails, RetryPolicy(attempts=1))

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("attempts", "base", "maximum"), [(0, 0.1, 1.0), (1, -1.0, 1.0), (1, 2.0, 1.0)]
)
def test_rejects_an_invalid_policy(attempts: int, base: float, maximum: float) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(attempts=attempts, base_delay_seconds=base, max_delay_seconds=maximum)
