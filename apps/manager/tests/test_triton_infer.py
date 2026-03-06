from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from classes.triton.infer import TritonInfer
from classes.triton.tritonerrors import TritonInferenceFailed


def test_build_grpc_and_http_inputs_bytes_and_numeric():
    """_build_grpc_inputs/_build_http_inputs should map dims, datatype and values correctly.

    We patch grpc/http InferInput to avoid depending on real Triton dtype validation.
    """
    inputs = [
        {"name": "text", "dims": 1, "type": "BYTES", "value": "hello"},
        {"name": "score", "dims": [1], "type": "FP32", "value": 0.42},
    ]

    class FakeInferInput:
        def __init__(self, name, shape, datatype):
            self.name = name
            self.shape = shape
            self.datatype = datatype
            self.data = None

        def set_data_from_numpy(self, arr):
            self.data = arr

    with (
        patch("classes.triton.infer.grpcclient.InferInput", FakeInferInput),
        patch("classes.triton.infer.httpclient.InferInput", FakeInferInput),
    ):
        grpc_inputs = TritonInfer._build_grpc_inputs(inputs)
        http_inputs = TritonInfer._build_http_inputs(inputs)

    assert len(grpc_inputs) == 2
    assert len(http_inputs) == 2

    # BYTES case: numpy object array with encoded string
    grpc_bytes = grpc_inputs[0].data
    http_bytes = http_inputs[0].data
    assert isinstance(grpc_bytes, np.ndarray) and grpc_bytes.dtype == object
    assert isinstance(http_bytes, np.ndarray) and http_bytes.dtype == object
    assert grpc_bytes[0] == b"hello"
    assert http_bytes[0] == b"hello"

    # Numeric case: standard numpy array containing the scalar value
    assert np.allclose(grpc_inputs[1].data, np.array([0.42]))
    assert np.allclose(http_inputs[1].data, np.array([0.42]))


def test_decode_output_bytes_and_fp16():
    """decode_output must handle BYTES and FP16 conversion."""
    # BYTES: single value → scalar string
    arr_bytes = np.array([b"hello"], dtype=object)
    result = MagicMock()
    result.as_numpy.return_value = arr_bytes

    out = TritonInfer.decode_output(result, "output")
    assert out == "hello"

    # FP16: cast to FP32 then list
    arr_fp16 = np.array([1.0, 2.0], dtype=np.float16)
    result2 = MagicMock()
    result2.as_numpy.return_value = arr_fp16

    out2 = TritonInfer.decode_output(result2, "output")
    assert isinstance(out2, list)
    assert np.allclose(out2, [1.0, 2.0])


def test_decode_response_builds_dict_from_response():
    """decode_response should inspect result.get_response()['outputs']."""
    mock_result = MagicMock()
    mock_result.get_response.return_value = {
        "outputs": [
            {"name": "out1"},
            {"name": "out2"},
        ]
    }

    # Make decode_output deterministic
    def fake_decode_output(res, name):
        return f"value-{name}"

    orig = TritonInfer.decode_output
    TritonInfer.decode_output = staticmethod(fake_decode_output)  # type: ignore[assignment]
    try:
        decoded = TritonInfer.decode_response(mock_result)
    finally:
        TritonInfer.decode_output = orig  # restore

    assert decoded == {"out1": "value-out1", "out2": "value-out2"}


def test_infer_success_and_error():
    """infer wraps http_client.infer and raises TritonInferenceFailed on error."""
    ti = TritonInfer()

    http_client = MagicMock()
    http_client.infer.return_value = "raw-result"

    result = ti.infer(http_client, "model-a", inputs=[])
    assert result == "raw-result"
    http_client.infer.assert_called_once()

    http_client_error = MagicMock()

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    http_client_error.infer.side_effect = _raise

    with pytest.raises(TritonInferenceFailed) as exc:
        ti.infer(http_client_error, "model-b", inputs=[])

    assert "boom" in str(exc.value)
    assert exc.value.model_name == "model-b"


def test_stream_success_single_chunk():
    """stream should pass decoded chunk to on_chunk and stop cleanly."""
    ti = TritonInfer()
    on_chunk_calls = []

    def on_chunk(piece: str):
        on_chunk_calls.append(piece)

    # Fake grpc client with minimal API
    class FakeGrpcClient:
        def __init__(self):
            self._callback = None
            self.started = False
            self.stopped = False

        def start_stream(self, callback):
            self._callback = callback
            self.started = True

        def async_stream_infer(self, model_name, inputs):
            # Simulate one valid chunk
            result = MagicMock()
            result.as_numpy.return_value = np.array([b"hi"], dtype=object)
            self._callback(result, None)
            # Then a final undecodable response to signal end
            bad_result = MagicMock()
            bad_result.as_numpy.side_effect = Exception("end")
            self._callback(bad_result, None)

        def stop_stream(self):
            self.stopped = True

    client = FakeGrpcClient()

    ti.stream(client, "model-x", inputs=[], on_chunk=on_chunk, timeout=5)

    assert client.started is True
    assert client.stopped is True
    assert on_chunk_calls == ["hi"]


def test_stream_errors_and_timeout():
    """stream should surface TritonInferenceFailed on callback error or timeout."""
    ti = TritonInfer()

    # Case 1: error in callback → TritonInferenceFailed
    class ErrorClient:
        def __init__(self):
            self._callback = None

        def start_stream(self, callback):
            self._callback = callback

        def async_stream_infer(self, model_name, inputs):
            self._callback(None, RuntimeError("stream-error"))

        def stop_stream(self):
            pass

    with pytest.raises(TritonInferenceFailed) as exc1:
        ti.stream(
            ErrorClient(), "model-y", inputs=[], on_chunk=lambda _: None, timeout=5
        )
    assert "stream-error" in str(exc1.value)

    # Case 2: timeout waiting on done event
    class HangClient:
        def start_stream(self, callback):
            # Never call callback
            self._cb = callback

        def async_stream_infer(self, model_name, inputs):
            pass

        def stop_stream(self):
            pass

    with pytest.raises(TritonInferenceFailed) as exc2:
        ti.stream(
            HangClient(), "model-z", inputs=[], on_chunk=lambda _: None, timeout=0
        )
    assert "timed out" in str(exc2.value)
