import pytest

from classes.triton.inference_orchestrator import TritonInference
from classes.triton.tritonerrors import TritonNetworkError, TritonTimeoutError


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("timed out", TritonTimeoutError),
        ("Timeout while reading from socket", TritonTimeoutError),
        ("deadline exceeded", TritonTimeoutError),
        ("connection refused", TritonNetworkError),
        ("connection reset by peer", TritonNetworkError),
        ("unreachable host", TritonNetworkError),
    ],
)
def test_error_classification_string_signals(msg: str, expected):
    exc = RuntimeError(msg)
    err = TritonInference._classify_error(model_name="m", exc=exc)
    assert isinstance(err, expected)
    # Retriable errors must be retriable=True for scheduler/backoff logic.
    assert getattr(err, "retriable", None) is True

