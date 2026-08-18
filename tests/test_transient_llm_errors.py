import httpx
import pytest

from app.llm.services.transient_llm_errors import is_transient_llm_error


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ReadTimeout("timed out"), True),
        (httpx.ConnectTimeout("timed out"), True),
        (RuntimeError("Malformed extraction response."), False),
        (RuntimeError("ReadTimeout: something"), True),
    ],
)
def test_is_transient_llm_error(exc: BaseException, expected: bool) -> None:
    assert is_transient_llm_error(exc) is expected
