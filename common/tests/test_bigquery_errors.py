import pytest

from common.bigquery import is_transient_exception
from common.tests.fakes import HttpError


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_http_codes(code: int) -> None:
    assert is_transient_exception(HttpError(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409])
def test_permanent_http_codes(code: int) -> None:
    assert is_transient_exception(HttpError(code)) is False


def test_network_trouble_is_transient() -> None:
    assert is_transient_exception(TimeoutError()) is True
    assert is_transient_exception(ConnectionResetError()) is True


def test_local_file_problems_and_programming_errors_are_not_transient() -> None:
    assert is_transient_exception(FileNotFoundError()) is False
    assert is_transient_exception(PermissionError()) is False
    assert is_transient_exception(ValueError("bug")) is False
